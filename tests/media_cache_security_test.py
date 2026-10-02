"""Synthetic regression for cached authenticated media responses."""

import base64

import pytest
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.urls import reverse
from wagtail.models import PageViewRestriction

from cast.models import Episode


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


def podlove_url(episode, *, post_id=None, episode_id=None):
    kwargs = {"pk": episode.podcast_audio.pk}
    if post_id is not None:
        kwargs["post_id"] = post_id
    url = reverse("cast:api:audio_podlove_detail", kwargs=kwargs)
    if episode_id is not None:
        url += f"?episode_id={episode_id}"
    return url


def assert_private(response):
    assert response["Cache-Control"] == "private, no-store"
    assert {"Cookie", "Authorization"} <= {value.strip() for value in response["Vary"].split(",")}


@pytest.mark.django_db
@pytest.mark.parametrize("anchor", ["post", "episode", "bare"])
def test_draft_podlove_response_is_not_served_after_credentials_are_revoked(
    client, full_site_cache, episode, admin_user, anchor
):
    episode.live = False
    episode.save()
    admin_user.set_password("synthetic-password")
    admin_user.save()
    credentials = base64.b64encode(f"{admin_user.username}:synthetic-password".encode()).decode()
    kwargs = {f"{anchor}_id": episode.pk} if anchor != "bare" else {}
    url = podlove_url(episode, **kwargs)
    editor_response = client.get(url, HTTP_AUTHORIZATION=f"Basic {credentials}")
    assert editor_response.status_code == 200
    # Django's Authorization variation prevents a different user reusing the
    # response, but cannot recheck revoked credentials on the same cache key.
    assert client.get(url).status_code == 404
    admin_user.set_password("revoked-password")
    admin_user.save()
    revoked_response = client.get(url, HTTP_AUTHORIZATION=f"Basic {credentials}")
    cache.clear()
    fresh_revoked_response = client.get(url, HTTP_AUTHORIZATION=f"Basic {credentials}")
    assert fresh_revoked_response.status_code == 403
    assert revoked_response.status_code == fresh_revoked_response.status_code
    assert_private(editor_response)


@pytest.mark.django_db
def test_restricted_podlove_response_rechecks_group_membership(client, full_site_cache, episode, django_user_model):
    group = Group.objects.create(name="Synthetic permitted readers")
    user = django_user_model.objects.create_user("synthetic-reader", password="synthetic-password")
    user.groups.add(group)
    restriction = PageViewRestriction.objects.create(page=episode, restriction_type=PageViewRestriction.GROUPS)
    restriction.groups.add(group)
    client.force_login(user)
    url = podlove_url(episode, post_id=episode.pk)
    response = client.get(url)
    assert response.status_code == 200
    user.groups.remove(group)
    revoked_response = client.get(url)
    cache.clear()
    assert client.get(url).status_code == 404
    assert revoked_response.status_code == 404
    assert_private(response)


@pytest.mark.django_db
@pytest.mark.parametrize("private_anchor", ["post", "episode"])
def test_each_supplied_podlove_anchor_contributes_to_cache_policy(admin_client, episode, private_anchor):
    private_episode = episode.get_parent().add_child(
        instance=Episode(
            title="Synthetic private episode", slug="synthetic-private", podcast_audio=episode.podcast_audio
        )
    )
    PageViewRestriction.objects.create(page=private_episode, restriction_type=PageViewRestriction.LOGIN)
    anchors = {"post_id": episode.pk, "episode_id": episode.pk}
    anchors[f"{private_anchor}_id"] = private_episode.pk
    response = admin_client.get(podlove_url(episode, **anchors))
    assert response.status_code == 200
    assert_private(response)


@pytest.mark.django_db
def test_unrestricted_public_podlove_response_remains_cacheable(client, full_site_cache, episode):
    response = client.get(podlove_url(episode, post_id=episode.pk, episode_id=episode.pk))
    assert response.status_code == 200
    assert "private" not in response["Cache-Control"]
    assert "no-store" not in response["Cache-Control"]
    assert "max-age=60" in response["Cache-Control"]
