"""Synthetic full-site-cache boundary checks for legacy transcript/chapter views."""

from datetime import time

import pytest
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from wagtail.models import PageViewRestriction

from cast.devdata import create_transcript
from cast.models import ChapterMark

MARKER = "Synthetic private transcript phrase"
ENDPOINTS = ("podlove", "podcastindex", "vtt", "html-bare", "html-post", "html-slug", "chapters")


@pytest.fixture
def full_site_cache(settings):
    settings.MIDDLEWARE = [
        "django.middleware.cache.UpdateCacheMiddleware",
        *settings.MIDDLEWARE,
        "django.middleware.cache.FetchFromCacheMiddleware",
    ]
    settings.CACHE_MIDDLEWARE_SECONDS = 60
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def synthetic_transcript(episode):
    return create_transcript(
        audio=episode.podcast_audio,
        podlove={"transcripts": [{"start_ms": 0, "end_ms": 1000, "text": MARKER}]},
        vtt=f"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n{MARKER}\n",
        dote={
            "lines": [
                {"startTime": "00:00:00,000", "endTime": "00:00:01,000", "speakerDesignation": "", "text": MARKER}
            ]
        },
    )


@pytest.fixture(params=ENDPOINTS)
def media_endpoint(request, episode, post_with_audio, synthetic_transcript):
    transcript = synthetic_transcript
    ChapterMark.objects.create(audio=episode.podcast_audio, start=time(0, 1), title=MARKER)
    kind = request.param
    anchor = episode
    if kind in {"podlove", "podcastindex", "vtt"}:
        name = "cast:webvtt-transcript" if kind == "vtt" else f"cast:{kind}-transcript-json"
        url = reverse(name, kwargs={"pk": transcript.pk})
        url += f"?episode_id={episode.pk}"
    elif kind == "chapters":
        url = reverse("cast:chapters-json", kwargs={"pk": episode.podcast_audio.pk}) + f"?episode_id={episode.pk}"
    elif kind == "html-bare":
        url = reverse("cast:html-transcript-no-post", kwargs={"transcript_pk": transcript.pk})
    elif kind == "html-post":
        anchor = post_with_audio
        url = reverse("cast:html-transcript", kwargs={"transcript_pk": transcript.pk, "post_pk": anchor.pk})
    else:
        url = episode.get_transcript_url()
    return url, anchor, kind, transcript


def assert_private(response):
    assert response["Cache-Control"] == "private, no-store"
    assert {"Cookie", "Authorization"} <= {part.strip() for part in response["Vary"].split(",")}


@pytest.mark.django_db
@pytest.mark.parametrize("inherited", [False, True])
def test_private_media_rechecks_group_revocation(
    client, full_site_cache, media_endpoint, django_user_model, inherited
):
    url, anchor, kind, _ = media_endpoint
    group = Group.objects.create(name="Synthetic transcript readers")
    user = django_user_model.objects.create_user("synthetic-reader", password="synthetic-password")
    user.groups.add(group)
    restriction = PageViewRestriction.objects.create(
        page=anchor.get_parent() if inherited else anchor,
        restriction_type=PageViewRestriction.GROUPS,
    )
    restriction.groups.add(group)
    client.force_login(user)
    response = client.get(url)
    assert response.status_code == 200
    assert MARKER in response.content.decode()
    assert Client().get(url).status_code == 404
    user.groups.remove(group)
    revoked = client.get(url)
    cache.clear()
    assert client.get(url).status_code == 404
    assert revoked.status_code == 404
    assert MARKER not in revoked.content.decode()
    if not kind.startswith("html"):
        assert_private(response)


@pytest.mark.django_db
def test_public_media_cache_and_restriction_transition(client, full_site_cache, media_endpoint, mocker):
    """Previously public cache entries retain their TTL; purging rechecks access."""
    from cast.views import chapters as chapter_views, transcript as transcript_views

    url, anchor, kind, _ = media_endpoint
    if kind == "chapters":
        authorization = mocker.spy(chapter_views, "authorize_audio_access")
    elif kind == "html-slug":
        authorization = mocker.spy(transcript_views, "request_may_view_page")
    else:
        authorization = mocker.spy(transcript_views, "authorize_transcript_access")
    public_response = client.get(url)
    assert public_response.status_code == 200
    assert MARKER in public_response.content.decode()
    assert authorization.call_count == 1
    repeated = client.get(url)
    assert repeated.status_code == 200
    assert MARKER in repeated.content.decode()
    if not kind.startswith("html"):
        assert repeated.content == public_response.content
    # Standard HTML templates set CSRF cookies, which prevents full-site-cache
    # admission on this Django version. The raw successful media is cacheable.
    assert authorization.call_count == (2 if kind.startswith("html") else 1)
    PageViewRestriction.objects.create(page=anchor, restriction_type=PageViewRestriction.LOGIN)
    warm = client.get(url)
    cache.clear()
    assert client.get(url).status_code == 404
    assert warm.status_code == (404 if kind.startswith("html") else 200)
    if not kind.startswith("html"):
        assert MARKER in warm.content.decode()
        assert "private" not in public_response["Cache-Control"]
        assert "no-store" not in public_response["Cache-Control"]


@pytest.mark.django_db
def test_private_media_can_become_public(client, full_site_cache, media_endpoint, django_user_model):
    url, anchor, kind, _ = media_endpoint
    user = django_user_model.objects.create_user("synthetic-member", password="synthetic-password")
    restriction = PageViewRestriction.objects.create(page=anchor, restriction_type=PageViewRestriction.LOGIN)
    client.force_login(user)
    private = client.get(url)
    assert private.status_code == 200
    assert MARKER in private.content.decode()
    assert Client().get(url).status_code == 404
    restriction.delete()
    public = Client().get(url)
    assert public.status_code == 200
    assert MARKER in public.content.decode()
    if not kind.startswith("html"):
        assert_private(private)
        assert "private" not in public["Cache-Control"]
        assert "no-store" not in public["Cache-Control"]


@pytest.mark.django_db
def test_episode_html_redirect_follow_rechecks_restricted_access(
    client, full_site_cache, episode, synthetic_transcript, django_user_model
):
    transcript = synthetic_transcript
    user = django_user_model.objects.create_user("synthetic-html-reader", password="synthetic-password")
    group = Group.objects.create(name="Synthetic HTML readers")
    user.groups.add(group)
    restriction = PageViewRestriction.objects.create(page=episode, restriction_type=PageViewRestriction.GROUPS)
    restriction.groups.add(group)
    client.force_login(user)
    url = reverse("cast:html-transcript", kwargs={"transcript_pk": transcript.pk, "post_pk": episode.pk})
    response = client.get(url, follow=True)
    assert response.status_code == 200
    assert MARKER in response.content.decode()
    assert response.redirect_chain == [(episode.get_transcript_url(), 302)]
    assert Client().get(url, follow=True).status_code == 404
    user.groups.remove(group)
    revoked = client.get(url, follow=True)
    cache.clear()
    assert client.get(url, follow=True).status_code == 404
    assert revoked.status_code == 404
    assert MARKER not in revoked.content.decode()
