"""Opt-in disposable feed spike; reuse the isolated typeahead seeder.

Set CAST_BENCHMARK_DB_NAME explicitly to a new disposable database, using
scripts.typeahead_benchmark_settings. Run: uv run python -m scripts.benchmark_feeds.
Never point this at a consumer database. Empty bodies make results a lower bound,
not a realistic media-heavy podcast benchmark. This does not run in normal CI.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import tracemalloc
from pathlib import Path
from unittest.mock import patch

if not os.environ.get("CAST_BENCHMARK_DB_NAME"):
    raise RuntimeError("Set CAST_BENCHMARK_DB_NAME to an explicit disposable benchmark database")

# Refuse consumer settings and non-disposable targets before Django can connect.
if (
    os.environ.get("DJANGO_SETTINGS_MODULE", "scripts.typeahead_benchmark_settings")
    != "scripts.typeahead_benchmark_settings"
):
    raise RuntimeError("Only isolated benchmark settings are allowed")
if os.environ.get("CAST_BENCHMARK_DB_ENGINE", "sqlite") == "postgresql":
    target = Path(os.environ.get("CAST_BENCHMARK_DB_HOST", ""))
    if os.environ["CAST_BENCHMARK_DB_NAME"] != "cast_feed_spike":
        raise RuntimeError("PostgreSQL database must be named cast_feed_spike")
else:
    target = Path(os.environ["CAST_BENCHMARK_DB_NAME"]).parent
if (
    not target.is_absolute()
    or not target.name.startswith("cast-feed-spike.")
    or target.resolve().parent
    not in {
        Path("/tmp").resolve(),
    }
):
    raise RuntimeError("Use a mktemp -d /tmp/cast-feed-spike.XXXXXX directory (SQLite file or PostgreSQL socket)")
os.environ["DJANGO_SETTINGS_MODULE"] = "scripts.typeahead_benchmark_settings"

import django  # noqa: E402

django.setup()

from django.contrib.sites.models import Site as DjangoSite  # noqa: E402
from django.core.cache import cache  # noqa: E402
from django.db import connection  # noqa: E402
from django.db.models import Q  # noqa: E402
from django.test import Client, RequestFactory, override_settings  # noqa: E402
from django.test.utils import CaptureQueriesContext  # noqa: E402
from django.urls import reverse  # noqa: E402

from cast import appsettings  # noqa: E402
from cast.feeds import LatestEntriesFeed, RepositoryMixin  # noqa: E402
from cast.models import Post  # noqa: E402
from cast.models.repository import FeedContext  # noqa: E402
from cast.models.repository.builders import data_for_blog_cachable  # noqa: E402
from scripts import benchmark_typeahead as seed  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection-only", action="store_true")
    parser.add_argument(
        "--candidate-index", action="store_true", help="Create an index only in this disposable database"
    )
    args = parser.parse_args()
    seed.seed([1_000, 10_000])
    DjangoSite.objects.update_or_create(pk=1, defaults={"domain": "localhost", "name": "benchmark"})
    with connection.cursor() as cursor:
        if args.candidate_index:
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS cast_feed_spike_visible_pk ON cast_post (visible_date, page_ptr_id)"
            )
        cursor.execute("ANALYZE")
    client = Client()
    for size in [1_000, 10_000]:
        blog = seed.Blog.objects.get(slug=f"{seed.BENCHMARK_SLUG_PREFIX}{size}")
        queryset = Post.objects.live().public().descendant_of(blog).order_by("-visible_date", "-pk")
        assert queryset.count() == size, "Unexpected public archive size"
        boundary = queryset.values_list("visible_date", "pk")[size * 9 // 10]
        deep = queryset.filter(Q(visible_date__lt=boundary[0]) | Q(visible_date=boundary[0], pk__lt=boundary[1]))
        tuple_deep = queryset.extra(
            where=["(cast_post.visible_date, cast_post.page_ptr_id) < (%s, %s)"], params=boundary
        )
        for label, selection in [("head", queryset[:101]), ("deep", deep[:101]), ("tuple-deep", tuple_deep[:101])]:
            started = time.perf_counter()
            selected = list(selection.values_list("pk", flat=True))
            selection_seconds = time.perf_counter() - started
            print(
                json.dumps(
                    {
                        "db": connection.vendor,
                        "size": size,
                        "selection": label,
                        "candidate_index": args.candidate_index,
                        "selected": len(selected),
                        "seconds": selection_seconds,
                        "plan": selection.values_list("pk", flat=True).explain(),
                    }
                ),
                flush=True,
            )
        if args.selection_only:
            continue
        for repository in ["default", "django"]:
            appsettings.CAST_REPOSITORY = repository
            url = reverse("cast:latest_entries_feed", kwargs={"slug": blog.slug})
            cache.clear()
            for mode in ["cold", "warm", "selected-prototype"]:
                rendered = 0
                original = RepositoryMixin.item_description

                def description(self, item):
                    nonlocal rendered
                    rendered += 1
                    return original(self, item)

                tracemalloc.start()
                started = time.perf_counter()
                with (
                    CaptureQueriesContext(connection) as queries,
                    patch.object(RepositoryMixin, "item_description", description),
                ):
                    if mode == "selected-prototype":
                        request = RequestFactory().get(url, HTTP_HOST="localhost")
                        selected_ids = list(queryset.values_list("pk", flat=True)[:101])
                        page = queryset.filter(pk__in=selected_ids[:100])
                        if repository == "default":
                            data = data_for_blog_cachable(
                                request=request, blog=blog, post_queryset=page, is_paginated=False
                            )
                            data["blog_url"] = blog.get_url(request=request)
                            context = FeedContext.create_from_cachable_data(data=data)
                        else:
                            context = FeedContext.create_from_django_models(
                                request=request, blog=blog, post_queryset=page
                            )
                        response = LatestEntriesFeed(repository=context)(request, slug=blog.slug)
                    else:
                        response = client.get(url, HTTP_HOST="localhost")
                elapsed = time.perf_counter() - started
                _, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                assert response.status_code == 200
                assert response.content.count(b"<item>") == (100 if mode == "selected-prototype" else size)
                assert rendered == (100 if mode == "selected-prototype" else 0 if mode == "warm" else size)
                print(
                    json.dumps(
                        {
                            "db": connection.vendor,
                            "size": size,
                            "repository": repository,
                            "cache": mode,
                            "seconds": round(elapsed, 3),
                            "queries": len(queries),
                            "rendered": rendered,
                            "bytes": len(response.content),
                            "python_peak_mib": round(peak / 1024**2, 2),
                        }
                    ),
                    flush=True,
                )


if __name__ == "__main__":
    with override_settings(ALLOWED_HOSTS=["localhost"]):
        main()
