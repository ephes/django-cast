"""Unverified caches admit posts/uploads with best-effort sequential limits."""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.core.cache import caches
from django.core.cache.backends.locmem import LocMemCache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import RequestFactory
from django.urls import reverse

from cast import cache_policy, media_ingest
from cast.comments.throttle import comment_post_retry_after
from tests.comments.comment_post_rate_limit_helpers import comment_count, post_ajax, post_plain


class UnverifiedCache(LocMemCache):
    """A custom subclass does not inherit the atomic capability guarantee."""


@pytest.fixture(
    params=[
        "django.core.cache.backends.filebased.FileBasedCache",
        "django.core.cache.backends.db.DatabaseCache",
        "django.core.cache.backends.dummy.DummyCache",
        "tests.cache_fallback_test.UnverifiedCache",
    ]
)
def fallback_cache(request, settings, tmp_path, db, monkeypatch):
    backend = request.param
    location = "fallback_" + uuid4().hex if backend.endswith("DatabaseCache") else str(tmp_path)
    settings.CACHES = {"default": {"BACKEND": backend, "LOCATION": location}}
    settings.CAST_COMMENTS_POST_RATE_LIMIT = 2
    settings.CAST_COMMENTS_POST_RATE_WINDOW = 600
    monkeypatch.setattr(cache_policy, "_warned", set())
    if backend.endswith("DatabaseCache"):
        call_command("createcachetable", location, verbosity=0)
    return caches["default"]


def is_dummy(cache):
    return type(cache).__name__ == "DummyCache"


def test_public_posts_work_and_share_best_effort_limit(fallback_cache, client, post, comments_enabled, caplog):
    address = "192.0.2.110"
    assert post_ajax(client, post, address).status_code == 200
    assert post_plain(client, post, address).status_code == 302
    assert post_ajax(client, post, address).status_code == (200 if is_dummy(fallback_cache) else 429)
    assert comment_count() == (3 if is_dummy(fallback_cache) else 2)
    warnings = [r for r in caplog.records if "Comment posting uses best-effort" in r.message]
    assert len(warnings) == 1
    assert warnings[0].levelname == "WARNING"
    assert "Redis/Memcached" in warnings[0].message


def test_comment_fallback_window_expires(fallback_cache, mocker):
    now = [1000.0]
    mocker.patch("rest_framework.throttling.SimpleRateThrottle.timer", side_effect=lambda: now[0])
    request = RequestFactory().post("/", REMOTE_ADDR="192.0.2.111")
    assert comment_post_retry_after(request) is None
    assert comment_post_retry_after(request) is None
    assert (comment_post_retry_after(request) is None) == is_dummy(fallback_cache)
    now[0] += 601
    assert comment_post_retry_after(request) is None


@pytest.mark.parametrize("method", ["get", "set"])
def test_comment_fallback_outage_refuses_and_logs(fallback_cache, mocker, caplog, method):
    mocker.patch.object(fallback_cache, method, side_effect=OSError("synthetic outage"))
    assert comment_post_retry_after(RequestFactory().post("/")) >= 1
    assert "Comment post cache reservation unavailable" in caplog.text


def test_upload_fallback_admits_and_limits(fallback_cache, caplog, mocker):
    set_lease = mocker.spy(fallback_cache, "set")
    user = SimpleNamespace(pk=123)
    with media_ingest.upload_lock(user, seconds=30):
        pass
    set_lease.assert_called_once_with(media_ingest.upload_lock_key(user), mocker.ANY, timeout=30)
    if is_dummy(fallback_cache):
        with media_ingest.upload_lock(user, seconds=30):
            pass
    else:
        assert fallback_cache.get(media_ingest.upload_lock_key(user)) is not None
        with pytest.raises(media_ingest.MediaUploadInProgress):
            with media_ingest.upload_lock(user, seconds=30):
                pytest.fail("repeat upload admitted before expiry")
        # Another user has an independent budget.
        with media_ingest.upload_lock(SimpleNamespace(pk=124), seconds=30):
            pass
    warnings = [r for r in caplog.records if "Audio/video upload uses best-effort" in r.message]
    assert len(warnings) == 1
    assert warnings[0].levelname == "WARNING"
    assert "Redis/Memcached" in warnings[0].message


@pytest.mark.parametrize("method", ["get", "set"])
def test_upload_fallback_outage_refuses_and_logs(fallback_cache, mocker, caplog, method):
    mocker.patch.object(fallback_cache, method, side_effect=OSError("synthetic outage"))
    with pytest.raises(OSError, match="synthetic outage"):
        with media_ingest.upload_lock(SimpleNamespace(pk=125)):
            pytest.fail("upload admitted during cache outage")
    assert "Media upload cache reservation unavailable" in caplog.text


def test_concurrent_first_warnings_are_emitted_once(mocker):
    mocker.patch.object(cache_policy, "_warned", set())
    logger = mocker.Mock()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: cache_policy.warn_best_effort(logger, "Synthetic admission"), range(20)))
    logger.warning.assert_called_once()


@pytest.mark.parametrize("media", ["audio", "video"])
def test_editor_upload_requests_use_fallback(
    fallback_cache, api_client, admin_user, m4a_audio, minimal_mp4, image_1px, media
):
    api_client.force_authenticate(user=admin_user)
    if media == "audio":
        field, upload = "m4a", m4a_audio
        endpoint = "cast:api:editor_media_audios"
    else:
        field, upload = "original", minimal_mp4
        endpoint = "cast:api:editor_media_videos"
    content = upload.read()
    poster = image_1px.read()

    def post_upload():
        data = {
            "title": "Fallback upload",
            field: SimpleUploadedFile(upload.name, content, content_type=upload.content_type),
        }
        if media == "video":
            data["poster"] = SimpleUploadedFile("poster.png", poster, content_type="image/png")
        return api_client.post(reverse(endpoint), data, format="multipart")

    first = post_upload()
    assert first.status_code == 201, first.content
    second = post_upload()
    assert second.status_code == (201 if is_dummy(fallback_cache) else 429), second.content
