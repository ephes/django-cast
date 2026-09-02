"""Seed and benchmark the proposed server-side typeahead query.

Examples::

    rm -f /tmp/cast-typeahead-benchmark.sqlite3
    uv run python -m scripts.benchmark_typeahead all

    CAST_BENCHMARK_DB_ENGINE=postgresql \
      uv run --with 'psycopg[binary]' python -m scripts.benchmark_typeahead all

The database must be isolated and disposable. The script runs migrations and
creates deterministic benchmark Blogs and Posts; it refuses to seed a database
that already contains non-benchmark Blogs.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Any

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "scripts.typeahead_benchmark_settings")

import django  # noqa: E402

django.setup()

import wagtail  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.core.cache import cache  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.db import close_old_connections, connection, connections  # noqa: E402
from django.test.utils import CaptureQueriesContext  # noqa: E402
from django.utils import timezone  # noqa: E402
from taggit.models import Tag  # noqa: E402
from wagtail.models import Collection, Locale, Page, PageViewRestriction, Site  # noqa: E402
from wagtail.search.backends import get_search_backend  # noqa: E402

from cast.models import Blog, Post  # noqa: E402
from cast.models.pages import PostTag  # noqa: E402
from cast.models.snippets import PostCategory  # noqa: E402
from cast.search_suggestions import get_search_suggestions  # noqa: E402

BENCHMARK_SLUG_PREFIX = "typeahead-benchmark-"
TITLE_STEMS = (
    "Python performance",
    "Django testing",
    "Hello world",
    "Podcast architecture",
    "Typeahead design",
    "Search indexing",
    "Async workflows",
    "PostgreSQL tuning",
)
DEFAULT_SIZES = (100, 1_000, 10_000)
MAX_RESPONSE_BYTES = 10 * 1024
MAX_QUERY_COUNT = 5
MAX_WARM_P95_MS = 150.0
MAX_WARM_P99_MS = 300.0
MAX_CONCURRENT_P95_MS = 300.0


@dataclass(frozen=True)
class QueryCase:
    name: str
    search: str
    date_facets: str = ""
    tag_facets: str = ""
    category_facets: str = ""


@dataclass(frozen=True)
class Sample:
    elapsed_ms: float
    query_count: int
    payload_bytes: int
    result_count: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("seed", "benchmark", "all"))
    parser.add_argument("--sizes", nargs="+", type=int, default=list(DEFAULT_SIZES))
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--cold-iterations", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=10)
    return parser.parse_args()


def ensure_benchmark_database() -> tuple[Site, Any]:
    call_command("migrate", interactive=False, verbosity=0)

    locale, _created = Locale.objects.get_or_create(language_code="en")
    root = Page.get_first_root_node()
    if root is None:
        root = Page.add_root(instance=Page(title="Root", slug="root", locale=locale))
    if Collection.get_first_root_node() is None:
        Collection.add_root(instance=Collection(name="Root"))

    site = Site.objects.filter(is_default_site=True).first()
    if site is None:
        site = Site.objects.create(hostname="localhost", port=80, root_page=root, is_default_site=True)
    elif site.root_page_id != root.pk:
        site.root_page = root
        site.save(update_fields=["root_page"])

    user_model = get_user_model()
    user, _created = user_model.objects.get_or_create(username="typeahead-benchmark")
    return site, user


def refuse_non_benchmark_blogs() -> None:
    unexpected = Blog.objects.exclude(slug__startswith=BENCHMARK_SLUG_PREFIX).values_list("slug", flat=True)[:5]
    unexpected_slugs = list(unexpected)
    if unexpected_slugs:
        joined = ", ".join(unexpected_slugs)
        raise RuntimeError(f"Refusing to seed a database containing non-benchmark Blogs: {joined}")


def create_blog(site: Site, user: Any, size: int) -> Blog:
    slug = f"{BENCHMARK_SLUG_PREFIX}{size}"
    existing = Blog.objects.filter(slug=slug).first()
    if existing is not None:
        count = existing.unfiltered_published_posts.count()
        if count != size:
            raise RuntimeError(f"{slug} contains {count} public posts; expected {size}. Use a fresh database.")
        print(f"seed: {slug} already has {count} posts", file=sys.stderr)
        return existing

    blog = Blog(owner=user, title=f"Typeahead benchmark {size}", slug=slug)
    site.root_page.add_child(instance=blog)
    seed_posts(blog, user, size)
    return blog


def seed_posts(blog: Blog, user: Any, size: int) -> None:
    now = timezone.now()
    post_ids: list[int] = []
    total_to_create = size + 1
    print(f"seed: creating {size} public posts plus one restricted control under {blog.slug}", file=sys.stderr)

    for offset in range(total_to_create):
        stem = TITLE_STEMS[offset % len(TITLE_STEMS)]
        post = Post(
            owner=user,
            title=f"{stem} article {offset:05d}",
            slug=f"article-{offset:05d}",
            body="[]",
            visible_date=now - timedelta(days=offset % (36 * 30)),
        )
        blog.add_child(instance=post)
        post_ids.append(post.pk)
        if (offset + 1) % 500 == 0 or offset + 1 == total_to_create:
            print(f"seed: {blog.slug} {offset + 1}/{total_to_create}", file=sys.stderr)

    add_facets(post_ids)
    restricted = Post.objects.get(pk=post_ids[-1])
    PageViewRestriction.objects.create(page=restricted, restriction_type=PageViewRestriction.LOGIN)


def add_facets(post_ids: list[int]) -> None:
    python_tag, _created = Tag.objects.get_or_create(name="python", defaults={"slug": "python"})
    django_tag, _created = Tag.objects.get_or_create(name="django", defaults={"slug": "django"})
    tutorial, _created = PostCategory.objects.get_or_create(name="Tutorial", defaults={"slug": "tutorial"})
    news, _created = PostCategory.objects.get_or_create(name="News", defaults={"slug": "news"})

    tagged: list[PostTag] = []
    categorized: list[Any] = []
    category_through = Post.categories.through
    for offset, post_id in enumerate(post_ids):
        if offset % 2 == 0:
            tagged.append(PostTag(content_object_id=post_id, tag_id=python_tag.pk))
        if offset % 3 == 0:
            tagged.append(PostTag(content_object_id=post_id, tag_id=django_tag.pk))
        category = tutorial if offset % 5 == 0 else news
        categorized.append(category_through(post_id=post_id, postcategory_id=category.pk))

    PostTag.objects.bulk_create(tagged, batch_size=1_000)
    category_through.objects.bulk_create(categorized, batch_size=1_000)


def seed(sizes: list[int]) -> None:
    site, user = ensure_benchmark_database()
    refuse_non_benchmark_blogs()
    for size in sorted(set(sizes)):
        create_blog(site, user, size)


def query_cases() -> list[QueryCase]:
    current_month = timezone.now().strftime("%Y-%m")
    return [
        QueryCase("broad_two_character", "py"),
        QueryCase("selective_prefix", "djang"),
        QueryCase("no_match", "zz"),
        QueryCase("multiword_prefix", "python per"),
        QueryCase("tag_scoped", "py", tag_facets="python"),
        QueryCase("category_scoped", "di", category_facets="tutorial"),
        QueryCase("date_scoped", "he", date_facets=current_month),
        QueryCase(
            "combined_facets",
            "py",
            date_facets=current_month,
            tag_facets="python",
            category_facets="tutorial",
        ),
    ]


def suggestion_payload(blog_id: int, site: Site, case: QueryCase) -> dict[str, Any]:
    blog = Blog.objects.live().public().get(pk=blog_id)
    params = {
        "search": case.search,
        "date_facets": case.date_facets,
        "tag_facets": case.tag_facets,
        "category_facets": case.category_facets,
    }
    return get_search_suggestions(blog=blog, params=params, current_site=site)


def measure(blog_id: int, site: Site, case: QueryCase) -> Sample:
    with CaptureQueriesContext(connection) as queries:
        started = time.perf_counter()
        payload = suggestion_payload(blog_id, site, case)
        encoded = json.dumps(payload, separators=(",", ":")).encode()
        elapsed_ms = (time.perf_counter() - started) * 1_000
    return Sample(
        elapsed_ms=elapsed_ms,
        query_count=len(queries),
        payload_bytes=len(encoded),
        result_count=len(payload["suggestions"]),
    )


def percentile(values: list[float], percent: int) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, (len(ordered) * percent + 99) // 100 - 1))
    return ordered[index]


def summarize(samples: list[Sample]) -> dict[str, Any]:
    elapsed = [sample.elapsed_ms for sample in samples]
    return {
        "iterations": len(samples),
        "min_ms": min(elapsed),
        "mean_ms": statistics.fmean(elapsed),
        "p50_ms": percentile(elapsed, 50),
        "p95_ms": percentile(elapsed, 95),
        "p99_ms": percentile(elapsed, 99),
        "max_ms": max(elapsed),
        "query_count_min": min(sample.query_count for sample in samples),
        "query_count_max": max(sample.query_count for sample in samples),
        "payload_bytes_max": max(sample.payload_bytes for sample in samples),
        "result_count": samples[-1].result_count,
    }


def cold_measure(blog_id: int, site: Site, case: QueryCase) -> Sample:
    connections.close_all()
    cache.clear()
    close_old_connections()
    return measure(blog_id, site, case)


def concurrent_measure(blog_id: int, site_id: int, case: QueryCase, concurrency: int) -> list[Sample]:
    def run_one() -> Sample:
        close_old_connections()
        try:
            thread_site = Site.objects.get(pk=site_id)
            return measure(blog_id, thread_site, case)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        return list(executor.map(lambda _index: run_one(), range(concurrency)))


def database_version() -> str:
    with connection.cursor() as cursor:
        if connection.vendor == "sqlite":
            cursor.execute("SELECT sqlite_version()")
        else:
            cursor.execute("SELECT version()")
        row = cursor.fetchone()
    return str(row[0])


def benchmark(sizes: list[int], iterations: int, cold_iterations: int, concurrency: int) -> dict[str, Any]:
    site = Site.objects.get(is_default_site=True)
    report: dict[str, Any] = {
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "django": django.get_version(),
            "wagtail": wagtail.__version__,
            "database_vendor": connection.vendor,
            "database_version": database_version(),
            "search_backend": type(get_search_backend()).__module__ + "." + type(get_search_backend()).__name__,
        },
        "thresholds": {
            "max_query_count": MAX_QUERY_COUNT,
            "max_response_bytes": MAX_RESPONSE_BYTES,
            "max_warm_p95_ms": MAX_WARM_P95_MS,
            "max_warm_p99_ms": MAX_WARM_P99_MS,
            "max_concurrent_p95_ms": MAX_CONCURRENT_P95_MS,
        },
        "archives": {},
    }
    failures: list[str] = []

    for size in sorted(set(sizes)):
        blog = Blog.objects.get(slug=f"{BENCHMARK_SLUG_PREFIX}{size}")
        archive_cases: dict[str, Any] = {}
        for case in query_cases():
            measure(blog.pk, site, case)
            warm_samples = [measure(blog.pk, site, case) for _index in range(iterations)]
            cold_samples = [cold_measure(blog.pk, site, case) for _index in range(cold_iterations)]
            warm = summarize(warm_samples)
            cold = summarize(cold_samples)
            archive_cases[case.name] = {"case": asdict(case), "warm": warm, "application_cold": cold}

            if warm["query_count_max"] > MAX_QUERY_COUNT:
                failures.append(f"{size}/{case.name}: {warm['query_count_max']} queries")
            if warm["payload_bytes_max"] >= MAX_RESPONSE_BYTES:
                failures.append(f"{size}/{case.name}: {warm['payload_bytes_max']} response bytes")
            if size == max(sizes) and warm["p95_ms"] > MAX_WARM_P95_MS:
                failures.append(f"{size}/{case.name}: warm p95 {warm['p95_ms']:.2f} ms")
            if size == max(sizes) and warm["p99_ms"] > MAX_WARM_P99_MS:
                failures.append(f"{size}/{case.name}: warm p99 {warm['p99_ms']:.2f} ms")

        report["archives"][str(size)] = archive_cases

    largest_blog = Blog.objects.get(slug=f"{BENCHMARK_SLUG_PREFIX}{max(sizes)}")
    concurrent = summarize(
        concurrent_measure(largest_blog.pk, site.pk, QueryCase("broad_two_character", "py"), concurrency)
    )
    report["concurrent_largest_archive"] = concurrent
    if concurrent["p95_ms"] > MAX_CONCURRENT_P95_MS:
        failures.append(f"concurrent: p95 {concurrent['p95_ms']:.2f} ms")

    report["gate"] = {"passed": not failures, "failures": failures}
    return report


def main() -> int:
    args = parse_args()
    if any(size <= 0 for size in args.sizes):
        raise ValueError("All archive sizes must be positive")
    if min(args.iterations, args.cold_iterations, args.concurrency) <= 0:
        raise ValueError("Iteration and concurrency values must be positive")

    if args.command in {"seed", "all"}:
        seed(args.sizes)
    if args.command in {"benchmark", "all"}:
        report = benchmark(args.sizes, args.iterations, args.cold_iterations, args.concurrency)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["gate"]["passed"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
