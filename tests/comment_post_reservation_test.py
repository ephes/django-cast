"""Independent public requests atomically claim the remaining shared cache slot."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from django.core.cache import caches
from django.core.cache.backends.locmem import LocMemCache
from django.db import close_old_connections
from django.test import Client, RequestFactory

from cast.comments.throttle import comment_post_retry_after
from tests.comment_post_rate_limit_test import comment_count, post_ajax
from tests.factories import BlogFactory, PostFactory


@pytest.fixture
def reservation_cache(settings):
    settings.CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": uuid4().hex}
    }
    settings.CAST_COMMENTS_POST_RATE_LIMIT = 2
    settings.CAST_COMMENTS_POST_RATE_WINDOW = 600
    return caches["default"]


def race_at_final_slot(mocker):
    barrier = Barrier(2)
    original_get, original_add = LocMemCache.get, LocMemCache.add

    def get(cache, key, *args, **kwargs):
        value = original_get(cache, key, *args, **kwargs)
        if key.startswith("throttle_cast_comment_post_"):
            barrier.wait(5)
        return value

    def add(cache, key, *args, **kwargs):
        if key.endswith(":slot:1"):
            barrier.wait(5)
        return original_add(cache, key, *args, **kwargs)

    mocker.patch.object(LocMemCache, "get", get)
    mocker.patch.object(LocMemCache, "add", add)


def test_parallel_admission_reserves_only_one_remaining_slot(mocker, reservation_cache):
    request = RequestFactory().post("/", REMOTE_ADDR="192.0.2.90")
    assert comment_post_retry_after(request) is None
    race_at_final_slot(mocker)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: comment_post_retry_after(RequestFactory().post("/", REMOTE_ADDR="192.0.2.90")), range(2)
            )
        )
    assert sum(result is None for result in results) == 1
    # Remove the barriers before the sequential check.
    mocker.stopall()
    assert comment_post_retry_after(request) >= 1


@pytest.fixture
def concurrent_post(transactional_db, settings):
    from django.contrib.sites.models import Site as CommentSite
    from wagtail.models import Locale, Page, Site

    locale, _ = Locale.objects.get_or_create(language_code=settings.LANGUAGE_CODE)
    root = Page.get_first_root_node() or Page.add_root(title="Synthetic root", slug="root", locale=locale)
    Site.objects.update_or_create(is_default_site=True, defaults={"root_page": root, "hostname": "localhost"})
    CommentSite.objects.update_or_create(pk=settings.SITE_ID, defaults={"domain": "example.org", "name": "Synthetic"})
    blog = BlogFactory(parent=root, title="Synthetic blog", slug="synthetic-blog")
    return PostFactory(parent=blog, title="Synthetic post", slug="synthetic-post", body=[])


@pytest.mark.django_db(transaction=True)
def test_parallel_public_posts_create_only_one_comment_at_final_slot(
    mocker, reservation_cache, concurrent_post, comments_enabled
):
    post = concurrent_post
    address = "192.0.2.91"
    assert post_ajax(Client(), post, address).status_code == 200
    race_at_final_slot(mocker)

    def perform(_):
        close_old_connections()
        try:
            return post_ajax(Client(), post, address).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(perform, range(2)))
    assert sorted(results) == [200, 429]
    assert comment_count() == 2


@pytest.mark.parametrize("backend", ["dummy.DummyCache", "filebased.FileBasedCache", "db.DatabaseCache"])
def test_unsupported_cache_refuses_admission(settings, tmp_path, backend):
    settings.CAST_COMMENTS_POST_RATE_LIMIT = 2
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends." + backend, "LOCATION": str(tmp_path)}}
    request = RequestFactory().post("/", REMOTE_ADDR="192.0.2.92")
    assert comment_post_retry_after(request) >= 1


def test_cache_outage_refuses_admission(mocker, reservation_cache):
    mocker.patch.object(reservation_cache, "add", side_effect=OSError("synthetic outage"))
    assert comment_post_retry_after(RequestFactory().post("/", REMOTE_ADDR="192.0.2.93")) >= 1


def test_slots_expire_without_rejected_requests_extending_them(mocker, reservation_cache):
    from django.core.cache.backends import base, locmem

    now = [1000.0]
    mocker.patch.object(base.time, "time", side_effect=lambda: now[0])
    assert locmem.time.time() == 1000.0
    request = RequestFactory().post("/", REMOTE_ADDR="192.0.2.94")
    assert comment_post_retry_after(request) is None
    now[0] += 100
    assert comment_post_retry_after(request) is None
    now[0] += 499
    assert comment_post_retry_after(request) >= 1
    now[0] += 2
    assert comment_post_retry_after(request) is None
    assert comment_post_retry_after(request) >= 1


def test_cache_configuration_failure_refuses_admission(reservation_cache):
    from unittest.mock import patch

    with patch.object(type(caches), "__getitem__", side_effect=RuntimeError("unavailable configuration")):
        assert comment_post_retry_after(RequestFactory().post("/", REMOTE_ADDR="192.0.2.95")) >= 1


def test_trusted_proxy_identity_and_author_budget_stay_independent(settings, reservation_cache):
    from cast.comments.author_edits import rate_limited

    settings.REST_FRAMEWORK = {"NUM_PROXIES": 1}
    settings.CAST_COMMENTS_EDIT_RATE_LIMIT = 1
    request = RequestFactory().post("/", REMOTE_ADDR="192.0.2.96", HTTP_X_FORWARDED_FOR="192.0.2.97, 192.0.2.98")
    assert not rate_limited(request, "edit")
    assert rate_limited(request, "edit")
    assert comment_post_retry_after(request) is None
    assert comment_post_retry_after(request) is None
    same_client = RequestFactory().post("/", REMOTE_ADDR="192.0.2.99", HTTP_X_FORWARDED_FOR="192.0.2.100, 192.0.2.98")
    assert comment_post_retry_after(same_client) >= 1
    other_client = RequestFactory().post("/", HTTP_X_FORWARDED_FOR="192.0.2.101")
    assert comment_post_retry_after(other_client) is None
