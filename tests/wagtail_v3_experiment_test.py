"""Wagtail 8 v3 discovery, draft-write, and publication experiment."""

import threading
import time
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from typing import Any, Literal, Protocol

import pytest
from django.conf import settings
from django.contrib.auth.models import AbstractUser, Group, Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import close_old_connections, connection, transaction
from django.test import Client
from django.urls import NoReverseMatch, reverse
from django.urls.base import clear_url_caches
from django.utils import timezone as django_timezone
from wagtail import VERSION as WAGTAIL_VERSION
from wagtail.models import (
    Collection,
    GroupCollectionPermission,
    GroupPagePermission,
    Locale,
    Page,
    PageLogEntry,
    Revision,
)

if (
    WAGTAIL_VERSION < (8, 0)
    or "wagtail.api.v3" not in settings.INSTALLED_APPS
    or settings.ROOT_URLCONF != "tests.wagtail_v3_urls"
):
    pytest.skip("Wagtail v3 experiment settings are not active", allow_module_level=True)

from wagtail.images import get_image_model  # noqa: E402
from wagtail.locks import ScheduledForPublishLock  # noqa: E402
from wagtail.models import APIToken  # noqa: E402

from cast.content.media_refs import get_choosable_image  # noqa: E402
from cast.models import Episode, Post  # noqa: E402
from cast.publication import EPISODE_AUDIO_REQUIRED  # noqa: E402
from tests.conftest import create_1_px_image  # noqa: E402
from tests.factories import BlogFactory, EpisodeFactory, PostFactory, UserFactory  # noqa: E402
from tests.wagtail_v3_writable import (  # noqa: E402
    EPISODE_ONLY_WRITABLE_FIELDS,
    POST_WRITABLE_FIELDS,
    SCHEDULE_WRITABLE_FIELDS,
)

pytestmark = pytest.mark.django_db

COMMON_PAGE_FIELDS = {"title", "slug", "seo_title", "search_description", "show_in_menus"}
POST_FIELDS = COMMON_PAGE_FIELDS | {"visible_date", "cover_image", "cover_alt_text", "body", "tags", "categories"}
EPISODE_FIELDS = POST_FIELDS | {
    "podcast_audio",
    "episode_number",
    "episode_type",
    "season",
    "keywords",
    "explicit",
    "block",
}
NATIVE_OVERVIEW_BODY = [{"type": "overview", "value": [{"type": "paragraph", "value": "<p>Native body</p>"}]}]
WRITABLE_FIELDS = {
    Post: POST_WRITABLE_FIELDS,
    Episode: POST_WRITABLE_FIELDS | EPISODE_ONLY_WRITABLE_FIELDS,
}


class ClientResponse(Protocol):
    status_code: int

    def json(self) -> dict[str, Any]: ...


def _bearer_token(user: object) -> str:
    _token, plaintext = APIToken.create_token(user=user, name="Cast v3 experiment")
    return plaintext


def _schema(client: object, token: str, model: type[Post]) -> dict:
    response = client.get(
        reverse("wagtailapi_v3:get_schema_for_type", kwargs={"type_name": model._meta.label}),
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert response.status_code == 200
    return response.json()


def _assert_cast_write_response_failure(response: object, model: type[Post]) -> None:
    """Record the response-serialization failure after a v3 write commits."""
    assert response.status_code == 422
    locations = {tuple(error["loc"]) for error in response.json()["errors"]}
    assert {
        ("response", model._meta.label, "html_overview"),
        ("response", model._meta.label, "html_detail"),
    } <= locations


def _adapter_update(
    client,
    token: str,
    page: Post,
    base_revision_id: int,
    values: dict,
    *,
    require_unpublished: bool = False,
) -> object:
    url = reverse("wagtailapi_v3:cast_revision_update", kwargs={"page_id": page.pk})
    if require_unpublished:
        url = f"{url}?require_unpublished=true"
    return client.patch(
        url,
        values,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
        HTTP_IF_MATCH=f'"{base_revision_id}"',
    )


def _transition_latest_revision(page: Post, user: AbstractUser, state: Literal["published", "scheduled"]) -> Revision:
    page.unpublish(user=user)
    page.refresh_from_db()
    draft = page.get_latest_revision_as_object()
    draft.go_live_at = django_timezone.now() + timedelta(days=1) if state == "scheduled" else None
    revision = draft.save_revision(user=user)
    revision.publish(user=user)
    page.refresh_from_db()
    revision.refresh_from_db()
    if state == "published":
        assert page.live is True
    else:
        assert page.live is False
        assert revision.approved_go_live_at is not None
    assert page.latest_revision_id == revision.pk
    return revision


def _draft_episode(podcast, body: str, *, slug: str, audio=None, go_live_at=None) -> Episode:
    return EpisodeFactory(
        owner=podcast.owner,
        parent=podcast,
        title=slug.replace("-", " ").title(),
        slug=slug,
        live=False,
        first_published_at=None,
        podcast_audio=audio,
        go_live_at=go_live_at,
        body=body,
    )


def _page_permission_user(page: Page, *codenames: str) -> AbstractUser:
    user = UserFactory(is_staff=False)
    group = Group.objects.create(name=f"v3 page permissions {user.pk}")
    for codename in codenames:
        permission = Permission.objects.get(codename=codename, content_type__app_label="wagtailcore")
        GroupPagePermission.objects.create(group=group, page=page, permission=permission)
    user.groups.add(group)
    return user


def _publish_action(client, token: str, page: Post) -> ClientResponse:
    return client.post(
        reverse("wagtailapi_v3:pages_actions_publish", kwargs={"page_id": page.pk}),
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )


def _adapter_publish(client, token: str, page: Post, if_match: str | None) -> ClientResponse:
    headers = {} if if_match is None else {"HTTP_IF_MATCH": if_match}
    return client.post(
        reverse("wagtailapi_v3:cast_revision_publish", kwargs={"page_id": page.pk}),
        HTTP_AUTHORIZATION=f"Bearer {token}",
        **headers,
    )


def _save_cover_revision(page: Post, user: AbstractUser, cover_alt_text: str) -> Revision:
    draft = page.get_latest_revision_as_object()
    draft.cover_alt_text = cover_alt_text
    return draft.save_revision(user=user)


def _publish_log_count(page: Post) -> int:
    return PageLogEntry.objects.filter(page_id=page.pk, action="wagtail.publish").count()


def _assert_audio_required(response: ClientResponse) -> None:
    assert response.status_code == 422
    # This test-only v3 endpoint inherits Wagtail's stdlib-derived problem title.
    # HTTP 422's phrase changed in Python 3.14; status and domain error stay fixed.
    assert response.json() == {
        "type": "about:blank",
        "title": HTTPStatus(422).phrase,
        "status": 422,
        "detail": "Validation failed",
        "errors": [{"msg": str(EPISODE_AUDIO_REQUIRED)}],
    }


def test_normal_test_urls_do_not_mount_wagtail_v3(settings) -> None:
    settings.ROOT_URLCONF = "tests.urls"
    clear_url_caches()
    try:
        with pytest.raises(NoReverseMatch):
            reverse("wagtailapi_v3:list_schemas")
    finally:
        clear_url_caches()


def test_schema_discovery_requires_a_bearer_token(client, admin_user) -> None:
    url = reverse("wagtailapi_v3:list_schemas")

    assert client.get(url).status_code == 401
    client.force_login(admin_user)
    assert client.get(url).status_code == 401

    token = _bearer_token(admin_user)
    response = client.get(url, HTTP_AUTHORIZATION=f"Bearer {token}")

    assert response.status_code == 200
    discovered = {entry["name"] for entry in response.json()["types"]}
    assert {Post._meta.label, Episode._meta.label} <= discovered


@pytest.mark.parametrize(
    ("model", "intended_fields", "read_cast_fields"),
    [
        (Post, POST_FIELDS, {"visible_date", "cover_image", "cover_alt_text", "body"}),
        (Episode, EPISODE_FIELDS, {"visible_date", "cover_image", "cover_alt_text", "body"}),
    ],
)
def test_schema_records_cast_field_inventory(client, admin_user, model, intended_fields, read_cast_fields) -> None:
    """Pin the deliberately narrow test-only write inventory."""
    schema = _schema(client, _bearer_token(admin_user), model)
    read_fields = set(schema["read"]["properties"])
    create_fields = set(schema["create"]["properties"])
    patch_fields = set(schema["patch"]["properties"])

    assert COMMON_PAGE_FIELDS <= create_fields
    assert COMMON_PAGE_FIELDS <= patch_fields
    assert read_cast_fields <= read_fields
    assert create_fields & (intended_fields - COMMON_PAGE_FIELDS) == WRITABLE_FIELDS[model]
    assert patch_fields & (intended_fields - COMMON_PAGE_FIELDS) == WRITABLE_FIELDS[model]
    if model is Episode:
        assert EPISODE_ONLY_WRITABLE_FIELDS <= read_fields


@pytest.mark.parametrize("fixture_name", ["post", "episode"])
def test_public_page_listing_exposes_live_cast_page_type(client, request, fixture_name) -> None:
    page = request.getfixturevalue(fixture_name)
    assert page.live is True
    response = client.get(reverse("wagtailapi_v3:list_pages"), {"type": page._meta.label})

    assert response.status_code == 200
    exposed = {(item["id"], item["meta"]["type"]) for item in response.json()["items"]}
    assert (page.id, page._meta.label) in exposed


@pytest.mark.parametrize(
    ("model", "parent_fixture", "values"),
    [
        (Post, "blog", {"cover_alt_text": "Draft post cover"}),
        (Episode, "podcast", {"episode_number": 17, "episode_type": "bonus"}),
    ],
)
def test_create_draft_commits_before_cast_response_serialization_fails(
    client, admin_user, request, model, parent_fixture, values
) -> None:
    parent = request.getfixturevalue(parent_fixture)
    title = f"v3 draft {model._meta.model_name}"
    response = client.post(
        reverse("wagtailapi_v3:create_page"),
        {
            "meta": {"type": model._meta.label, "parent_id": parent.pk},
            "title": title,
            **values,
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {_bearer_token(admin_user)}",
    )

    _assert_cast_write_response_failure(response, model)
    page = model.objects.get(title=title)
    draft = page.get_latest_revision_as_object()
    assert page.live is False
    for name, value in values.items():
        assert getattr(draft, name) == value
    if model is Episode:
        assert draft.podcast_audio_id is None


def test_partial_update_is_built_from_live_row_not_latest_draft(client, admin_user, post) -> None:
    post.cover_alt_text = "Live cover text"
    post.save(update_fields=["cover_alt_text"])
    live_row = Post.objects.get(pk=post.pk)
    draft = live_row.get_latest_revision_as_object()
    draft.cover_alt_text = "Newer draft cover text"
    newer_revision = draft.save_revision(user=admin_user)
    new_visible_date = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)

    response = client.patch(
        reverse("wagtailapi_v3:update_page", kwargs={"page_id": post.pk}),
        {"visible_date": new_visible_date.isoformat()},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {_bearer_token(admin_user)}",
    )

    _assert_cast_write_response_failure(response, Post)
    post.refresh_from_db()
    latest_draft = post.get_latest_revision_as_object()
    assert post.cover_alt_text == "Live cover text"
    assert post.latest_revision_id != newer_revision.id
    assert latest_draft.visible_date == new_visible_date
    assert latest_draft.cover_alt_text == "Live cover text"


@pytest.mark.parametrize(
    ("fixture_name", "preserved_field", "preserved_value", "updates"),
    [
        (
            "post",
            "cover_alt_text",
            "Newer draft cover text",
            {"visible_date": "2026-09-17T14:00:00Z"},
        ),
        ("episode", "episode_number", 23, {"episode_type": "bonus"}),
    ],
)
def test_revision_adapter_updates_latest_draft_with_truthful_response(
    client, admin_user, request, fixture_name, preserved_field, preserved_value, updates
) -> None:
    page = request.getfixturevalue(fixture_name)
    draft = page.get_latest_revision_as_object()
    setattr(draft, preserved_field, preserved_value)
    base_revision = draft.save_revision(user=admin_user)
    live_values = {name: getattr(type(page).objects.get(pk=page.pk), name) for name in updates}

    response = _adapter_update(client, _bearer_token(admin_user), page, base_revision.pk, updates)

    assert response.status_code == 200
    result = response.json()
    assert result["id"] == page.pk
    assert result["meta"]["type"] == page._meta.label
    assert result["base_revision_id"] == base_revision.pk
    assert result["latest_revision_id"] != base_revision.pk

    page.refresh_from_db()
    latest_draft = page.get_latest_revision_as_object()
    assert page.latest_revision_id == result["latest_revision_id"]
    assert getattr(latest_draft, preserved_field) == preserved_value
    for name, value in updates.items():
        expected = datetime.fromisoformat(value.replace("Z", "+00:00")) if name == "visible_date" else value
        assert getattr(latest_draft, name) == expected
        assert getattr(page, name) == live_values[name]


@pytest.mark.parametrize("fixture_name", ["post", "episode"])
def test_revision_adapter_allows_unpublished_page_when_draft_required(
    client, admin_user, request, fixture_name
) -> None:
    page = request.getfixturevalue(fixture_name)
    page.unpublish(user=admin_user)
    page.refresh_from_db()
    base_revision = page.get_latest_revision_as_object().save_revision(user=admin_user)

    response = _adapter_update(
        client,
        _bearer_token(admin_user),
        page,
        base_revision.pk,
        {"cover_alt_text": "Still a draft"},
        require_unpublished=True,
    )

    assert response.status_code == 200
    page.refresh_from_db()
    assert page.live is False
    assert page.latest_revision_id == response.json()["latest_revision_id"]
    assert page.get_latest_revision_as_object().cover_alt_text == "Still a draft"


def test_revision_adapter_rejects_stale_update_without_revision(client, admin_user, post) -> None:
    draft = post.get_latest_revision_as_object()
    draft.cover_alt_text = "First draft"
    stale_revision = draft.save_revision(user=admin_user)
    draft.cover_alt_text = "Current draft"
    current_revision = draft.save_revision(user=admin_user)
    revision_count = Revision.objects.filter(object_id=str(post.pk)).count()

    response = _adapter_update(
        client,
        _bearer_token(admin_user),
        post,
        stale_revision.pk,
        {"cover_alt_text": "Stale writer"},
    )

    assert response.status_code == 409
    assert response.json() == {
        "code": "revision_conflict",
        "current_revision_id": current_revision.pk,
        "submitted_base_revision_id": stale_revision.pk,
    }
    post.refresh_from_db()
    assert post.latest_revision_id == current_revision.pk
    assert post.get_latest_revision_as_object().cover_alt_text == "Current draft"
    assert Revision.objects.filter(object_id=str(post.pk)).count() == revision_count


def test_revision_adapter_rejects_invalid_form_without_revision(client, admin_user, episode) -> None:
    base_revision = episode.get_latest_revision_as_object().save_revision(user=admin_user)
    revision_count = Revision.objects.filter(object_id=str(episode.pk)).count()

    response = _adapter_update(
        client,
        _bearer_token(admin_user),
        episode,
        base_revision.pk,
        {"episode_type": "not-a-real-type"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Validation failed"
    assert {tuple(error["loc"]) for error in response.json()["errors"]} == {("episode_type",)}
    episode.refresh_from_db()
    assert episode.latest_revision_id == base_revision.pk
    assert Revision.objects.filter(object_id=str(episode.pk)).count() == revision_count


@pytest.mark.parametrize("fixture_name", ["post", "episode"])
@pytest.mark.parametrize("state", ["published", "scheduled"])
def test_stock_update_allows_live_draft_but_scheduled_lock_rejects(
    client, admin_user, request, fixture_name, state
) -> None:
    page = request.getfixturevalue(fixture_name)
    base_revision = _transition_latest_revision(page, admin_user, state)
    revision_count = page.revisions.count()
    if state == "scheduled":
        assert isinstance(Page.objects.get(pk=page.pk).specific.get_lock(), ScheduledForPublishLock)

    response = client.patch(
        reverse("wagtailapi_v3:update_page", kwargs={"page_id": page.pk}),
        {"cover_alt_text": f"Stock update after {state}"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {_bearer_token(admin_user)}",
    )

    page.refresh_from_db()
    base_revision.refresh_from_db()
    if state == "published":
        _assert_cast_write_response_failure(response, type(page))
        assert page.latest_revision_id != base_revision.pk
        assert page.revisions.count() == revision_count + 1
        assert page.get_latest_revision_as_object().cover_alt_text == f"Stock update after {state}"
        assert page.live is True
        assert page.live_revision_id == base_revision.pk
    else:
        assert response.status_code == 403
        assert page.latest_revision_id == base_revision.pk
        assert page.revisions.count() == revision_count
        assert page.get_latest_revision_as_object().cover_alt_text != f"Stock update after {state}"
        assert page.live is False
        assert base_revision.approved_go_live_at is not None


@pytest.mark.parametrize("fixture_name", ["post", "episode"])
@pytest.mark.parametrize(
    ("state", "expected_code"),
    [("published", "published_post"), ("scheduled", "scheduled_post")],
)
def test_revision_adapter_retains_draft_state_precondition(
    client, admin_user, request, fixture_name, state, expected_code
) -> None:
    page = request.getfixturevalue(fixture_name)
    base_revision = _transition_latest_revision(page, admin_user, state)
    revision_count = page.revisions.count()

    response = _adapter_update(
        client,
        _bearer_token(admin_user),
        page,
        base_revision.pk,
        {"cover_alt_text": "Must not be written"},
        require_unpublished=True,
    )

    assert response.status_code == 409
    expected_detail = (
        "This page is already live; the requested draft-only update was refused."
        if state == "published"
        else "This page is scheduled for publication; the requested draft-only update was refused."
    )
    assert response.json() == {"code": expected_code, "detail": expected_detail}
    page.refresh_from_db()
    assert page.latest_revision_id == base_revision.pk
    assert page.revisions.count() == revision_count
    assert page.get_latest_revision_as_object().cover_alt_text != "Must not be written"


def test_revision_adapter_requires_bearer_authentication(client, admin_user, post) -> None:
    base_revision = post.get_latest_revision_as_object().save_revision(user=admin_user)
    client.force_login(admin_user)

    response = client.patch(
        reverse("wagtailapi_v3:cast_revision_update", kwargs={"page_id": post.pk}),
        {"cover_alt_text": "Ignored"},
        content_type="application/json",
        HTTP_IF_MATCH=f'"{base_revision.pk}"',
    )

    assert response.status_code == 401
    post.refresh_from_db()
    assert post.latest_revision_id == base_revision.pk


@pytest.mark.parametrize("if_match", [None, "not-a-revision", '"not-a-revision"', 'W/"12"'])
def test_revision_adapter_requires_quoted_integer_base_revision(client, admin_user, post, if_match) -> None:
    headers = {} if if_match is None else {"HTTP_IF_MATCH": if_match}
    response = client.patch(
        reverse("wagtailapi_v3:cast_revision_update", kwargs={"page_id": post.pk}),
        {"cover_alt_text": "Ignored"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {_bearer_token(admin_user)}",
        **headers,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_base_revision"


def test_revision_adapter_reports_page_without_a_revision_as_stale(client, admin_user, post) -> None:
    assert post.latest_revision_id is None

    response = _adapter_update(
        client,
        _bearer_token(admin_user),
        post,
        0,
        {"cover_alt_text": "Ignored"},
    )

    assert response.status_code == 409
    assert response.json() == {
        "code": "revision_conflict",
        "current_revision_id": None,
        "submitted_base_revision_id": 0,
    }


def test_revision_adapter_does_not_expose_publish(client, admin_user, post) -> None:
    base_revision = post.get_latest_revision_as_object().save_revision(user=admin_user)
    revision_count = Revision.objects.filter(object_id=str(post.pk)).count()

    response = _adapter_update(
        client,
        _bearer_token(admin_user),
        post,
        base_revision.pk,
        {"meta": {"action": "publish"}, "cover_alt_text": "Ignored"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "publish_not_supported"
    post.refresh_from_db()
    assert post.latest_revision_id == base_revision.pk
    assert Revision.objects.filter(object_id=str(post.pk)).count() == revision_count


def test_create_and_publish_rejects_audio_less_episode_atomically(client, admin_user, podcast) -> None:
    title = "v3 audio-less create and publish"
    revision_count = Revision.objects.count()
    log_count = PageLogEntry.objects.count()

    response = client.post(
        reverse("wagtailapi_v3:create_page"),
        {
            "meta": {"type": Episode._meta.label, "parent_id": podcast.pk, "action": "publish"},
            "title": title,
            "body": NATIVE_OVERVIEW_BODY,
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {_bearer_token(admin_user)}",
    )

    _assert_audio_required(response)
    assert not Episode.objects.filter(title=title).exists()
    assert Revision.objects.count() == revision_count
    assert PageLogEntry.objects.count() == log_count


def test_edit_and_publish_rejects_audio_less_episode_without_revision(client, admin_user, podcast, body) -> None:
    episode = _draft_episode(podcast, body, slug="v3-audio-less-edit-publish")
    base_revision = episode.save_revision(user=admin_user)
    revision_count = episode.revisions.count()

    response = client.patch(
        reverse("wagtailapi_v3:update_page", kwargs={"page_id": episode.pk}),
        {"meta": {"action": "publish"}, "episode_type": "bonus"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {_bearer_token(admin_user)}",
    )

    _assert_audio_required(response)
    episode.refresh_from_db()
    assert episode.live is False
    assert episode.latest_revision_id == base_revision.pk
    assert episode.revisions.count() == revision_count


def test_standalone_publish_rejects_audio_less_episode(client, admin_user, podcast, body) -> None:
    episode = _draft_episode(podcast, body, slug="v3-audio-less-standalone-publish")
    revision = episode.save_revision(user=admin_user)

    response = _publish_action(client, _bearer_token(admin_user), episode)

    _assert_audio_required(response)
    episode.refresh_from_db()
    assert episode.live is False
    assert episode.live_revision_id is None
    assert episode.latest_revision_id == revision.pk


def test_standalone_publish_allows_episode_with_audio(client, admin_user, podcast, audio, body) -> None:
    episode = _draft_episode(podcast, body, slug="v3-valid-standalone-publish", audio=audio)
    revision = episode.save_revision(user=admin_user)

    response = _publish_action(client, _bearer_token(admin_user), episode)

    _assert_cast_write_response_failure(response, Episode)
    episode.refresh_from_db()
    assert episode.live is True
    assert episode.live_revision_id == revision.pk
    assert episode.podcast_audio_id == audio.pk


def test_v3_scheduled_revision_is_rechecked_after_audio_deletion(client, admin_user, podcast, audio, body) -> None:
    scheduled_for = (django_timezone.now() + timedelta(days=1)).replace(microsecond=0)
    episode = _draft_episode(
        podcast,
        body,
        slug="v3-scheduled-publication",
        audio=audio,
        go_live_at=scheduled_for,
    )
    revision = episode.save_revision(user=admin_user)

    response = _publish_action(client, _bearer_token(admin_user), episode)

    _assert_cast_write_response_failure(response, Episode)
    episode.refresh_from_db()
    revision.refresh_from_db()
    assert episode.live is False
    assert revision.approved_go_live_at == scheduled_for

    audio.delete()
    Revision.objects.filter(pk=revision.pk).update(approved_go_live_at=django_timezone.now() - timedelta(minutes=1))
    call_command("publish_scheduled", verbosity=0)

    episode.refresh_from_db()
    revision.refresh_from_db()
    assert episode.live is False
    assert episode.live_revision_id is None
    assert revision.approved_go_live_at is None
    assert PageLogEntry.objects.filter(page_id=episode.pk, action="cast.publish.rejected").exists()


def test_change_permission_is_tree_scoped_and_does_not_grant_publish(
    client, admin_user, site, blog, post, body
) -> None:
    other_blog = BlogFactory(owner=admin_user, parent=site.root_page, title="Other blog", slug="other-blog")
    other_post = PostFactory(
        owner=admin_user,
        parent=other_blog,
        title="Other post",
        slug="other-post",
        body=body,
    )
    post_revision = post.get_latest_revision_as_object().save_revision(user=admin_user)
    other_revision = other_post.get_latest_revision_as_object().save_revision(user=admin_user)
    user = _page_permission_user(blog, "change_page")
    token = _bearer_token(user)

    allowed = _adapter_update(client, token, post, post_revision.pk, {"cover_alt_text": "Allowed subtree"})
    denied = _adapter_update(client, token, other_post, other_revision.pk, {"cover_alt_text": "Wrong subtree"})
    publish = _publish_action(client, token, post)

    assert user.is_staff is False
    assert user.has_perm("wagtailadmin.access_admin") is False
    assert allowed.status_code == 200
    allowed_revision_id = allowed.json()["latest_revision_id"]
    assert allowed_revision_id != post_revision.pk
    assert Revision.objects.get(pk=allowed_revision_id).as_object().cover_alt_text == "Allowed subtree"
    assert denied.status_code == 403
    assert publish.status_code == 403
    other_post.refresh_from_db()
    assert other_post.latest_revision_id == other_revision.pk


def test_publish_permission_does_not_grant_draft_update(client, admin_user, podcast, audio, body) -> None:
    episode = _draft_episode(podcast, body, slug="v3-publish-only", audio=audio)
    revision = episode.save_revision(user=admin_user)
    user = _page_permission_user(podcast, "publish_page")
    token = _bearer_token(user)

    update = _adapter_update(client, token, episode, revision.pk, {"episode_type": "bonus"})
    publish = _publish_action(client, token, episode)

    assert update.status_code == 403
    _assert_cast_write_response_failure(publish, Episode)
    episode.refresh_from_db()
    assert episode.live is True
    assert episode.live_revision_id == revision.pk


def test_native_token_does_not_separate_write_and_publish_scopes(client, admin_user, blog, post) -> None:
    user = _page_permission_user(blog, "change_page", "publish_page")
    token = _bearer_token(user)
    base_revision = post.get_latest_revision_as_object().save_revision(user=admin_user)

    update = _adapter_update(client, token, post, base_revision.pk, {"cover_alt_text": "Same token"})
    assert update.status_code == 200
    publish = _publish_action(client, token, post)

    _assert_cast_write_response_failure(publish, Post)
    post.refresh_from_db()
    assert post.live_revision_id == update.json()["latest_revision_id"]
    token_fields = {field.name for field in APIToken._meta.get_fields()}
    assert "scope" not in token_fields
    assert "scopes" not in token_fields


@pytest.mark.parametrize("fixture_name", ["post", "episode"])
def test_stock_publish_ignores_selected_revision_and_publishes_newer_draft(
    client, admin_user, request, fixture_name
) -> None:
    page = request.getfixturevalue(fixture_name)
    token = _bearer_token(admin_user)
    selected = _save_cover_revision(page, admin_user, "Reviewed draft")
    listed = client.get(
        reverse("wagtailapi_v3:list_page_revisions", kwargs={"page_id": page.pk}),
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == selected.pk
    newer = _save_cover_revision(page, admin_user, "Unreviewed draft")

    # Stock v3 accepts no revision selector; an If-Match header is ignored.
    response = client.post(
        reverse("wagtailapi_v3:pages_actions_publish", kwargs={"page_id": page.pk}),
        HTTP_AUTHORIZATION=f"Bearer {token}",
        HTTP_IF_MATCH=f'"{selected.pk}"',
    )

    _assert_cast_write_response_failure(response, type(page))
    page.refresh_from_db()
    assert page.live is True
    assert page.live_revision_id == newer.pk
    assert page.latest_revision_id == newer.pk
    assert page.cover_alt_text == "Unreviewed draft"


def test_stock_publish_checks_newer_episode_revision_not_selected_one(
    client, admin_user, podcast, audio, body
) -> None:
    episode = _draft_episode(podcast, body, slug="v3-stock-newer-audio-less", audio=audio)
    selected = episode.save_revision(user=admin_user)
    draft = episode.get_latest_revision_as_object()
    draft.podcast_audio = None
    newer = draft.save_revision(user=admin_user)

    response = _publish_action(client, _bearer_token(admin_user), episode)

    _assert_audio_required(response)
    episode.refresh_from_db()
    selected.refresh_from_db()
    assert episode.live is False
    assert episode.live_revision_id is None
    assert episode.latest_revision_id == newer.pk
    assert selected.approved_go_live_at is None
    assert _publish_log_count(episode) == 0


@pytest.mark.parametrize("fixture_name", ["post", "episode"])
def test_revision_bound_publish_publishes_selected_latest_revision(client, admin_user, request, fixture_name) -> None:
    page = request.getfixturevalue(fixture_name)
    selected = _save_cover_revision(page, admin_user, "Reviewed draft")

    response = _adapter_publish(client, _bearer_token(admin_user), page, f'"{selected.pk}"')

    assert response.status_code == 200
    assert response.json() == {
        "id": page.pk,
        "meta": {"type": page._meta.label},
        "revision_id": selected.pk,
        "live": True,
        "live_revision_id": selected.pk,
    }
    page.refresh_from_db()
    assert page.live_revision_id == selected.pk
    assert page.latest_revision_id == selected.pk
    assert page.has_unpublished_changes is False
    assert page.cover_alt_text == "Reviewed draft"
    assert _publish_log_count(page) == 1


@pytest.mark.parametrize("fixture_name", ["post", "episode"])
def test_revision_bound_publish_rejects_stale_selection_without_publishing(
    client, admin_user, request, fixture_name
) -> None:
    page = request.getfixturevalue(fixture_name)
    live_revision_id = page.live_revision_id
    live_cover_alt_text = type(page).objects.get(pk=page.pk).cover_alt_text
    selected = _save_cover_revision(page, admin_user, "Reviewed draft")
    newer = _save_cover_revision(page, admin_user, "Unreviewed draft")
    revision_count = page.revisions.count()

    response = _adapter_publish(client, _bearer_token(admin_user), page, f'"{selected.pk}"')

    assert response.status_code == 409
    assert response.json() == {
        "code": "revision_conflict",
        "current_revision_id": newer.pk,
        "submitted_base_revision_id": selected.pk,
    }
    page.refresh_from_db()
    assert page.live_revision_id == live_revision_id
    assert page.latest_revision_id == newer.pk
    assert page.cover_alt_text == live_cover_alt_text
    assert page.revisions.count() == revision_count
    assert not page.revisions.filter(approved_go_live_at__isnull=False).exists()
    assert _publish_log_count(page) == 0


def test_revision_bound_publish_rejects_stale_episode_even_when_newer_is_valid(
    client, admin_user, podcast, audio, body
) -> None:
    episode = _draft_episode(podcast, body, slug="v3-bound-stale-audio-less")
    selected = episode.save_revision(user=admin_user)
    draft = episode.get_latest_revision_as_object()
    draft.podcast_audio = audio
    newer = draft.save_revision(user=admin_user)

    response = _adapter_publish(client, _bearer_token(admin_user), episode, f'"{selected.pk}"')

    assert response.status_code == 409
    assert response.json()["current_revision_id"] == newer.pk
    episode.refresh_from_db()
    assert episode.live is False
    assert episode.live_revision_id is None
    assert _publish_log_count(episode) == 0


def test_revision_bound_publish_applies_episode_policy_to_selected_revision(client, admin_user, podcast, body) -> None:
    episode = _draft_episode(podcast, body, slug="v3-bound-audio-less")
    selected = episode.save_revision(user=admin_user)

    response = _adapter_publish(client, _bearer_token(admin_user), episode, f'"{selected.pk}"')

    _assert_audio_required(response)
    episode.refresh_from_db()
    selected.refresh_from_db()
    assert episode.live is False
    assert episode.live_revision_id is None
    assert episode.latest_revision_id == selected.pk
    assert selected.approved_go_live_at is None
    assert _publish_log_count(episode) == 0


@pytest.mark.parametrize("if_match", [None, "not-a-revision", '"not-a-revision"', 'W/"12"'])
def test_revision_bound_publish_requires_quoted_integer_revision(client, admin_user, post, if_match) -> None:
    _save_cover_revision(post, admin_user, "Reviewed draft")

    response = _adapter_publish(client, _bearer_token(admin_user), post, if_match)

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_base_revision"
    post.refresh_from_db()
    assert post.live_revision_id is None
    assert _publish_log_count(post) == 0


def test_revision_bound_publish_requires_bearer_authentication(client, admin_user, post) -> None:
    selected = _save_cover_revision(post, admin_user, "Reviewed draft")
    client.force_login(admin_user)

    response = client.post(
        reverse("wagtailapi_v3:cast_revision_publish", kwargs={"page_id": post.pk}),
        HTTP_IF_MATCH=f'"{selected.pk}"',
    )

    assert response.status_code == 401
    post.refresh_from_db()
    assert post.live_revision_id is None


def test_revision_bound_publish_enforces_page_publish_permission(client, admin_user, site, blog, post, body) -> None:
    other_blog = BlogFactory(owner=admin_user, parent=site.root_page, title="Other blog", slug="other-blog")
    other_post = PostFactory(owner=admin_user, parent=other_blog, title="Other post", slug="other-post", body=body)
    selected = _save_cover_revision(post, admin_user, "Reviewed draft")
    other_selected = _save_cover_revision(other_post, admin_user, "Other reviewed draft")
    change_only = _bearer_token(_page_permission_user(blog, "change_page"))
    other_publisher = _bearer_token(_page_permission_user(other_blog, "publish_page"))

    model_denied = _adapter_publish(client, change_only, post, f'"{selected.pk}"')
    tree_denied = _adapter_publish(client, other_publisher, post, f'"{selected.pk + 1}"')
    allowed = _adapter_publish(client, other_publisher, other_post, f'"{other_selected.pk}"')

    assert model_denied.status_code == 403
    assert tree_denied.status_code == 403
    assert str(selected.pk) not in tree_denied.content.decode()
    assert allowed.status_code == 200
    post.refresh_from_db()
    other_post.refresh_from_db()
    assert post.live_revision_id is None
    assert _publish_log_count(post) == 0
    assert other_post.live_revision_id == other_selected.pk


def _unpublished_base_revision(page: Post, user: AbstractUser) -> Revision:
    page.unpublish(user=user)
    page.refresh_from_db()
    return page.get_latest_revision_as_object().save_revision(user=user)


def test_stock_page_schema_has_no_schedule_input(client, admin_user) -> None:
    token = _bearer_token(admin_user)
    stock_schema = client.get(
        reverse("wagtailapi_v3:get_schema_for_type", kwargs={"type_name": "cast.Blog"}),
        HTTP_AUTHORIZATION=f"Bearer {token}",
    ).json()
    opted_in_schemas = [_schema(client, token, model) for model in (Post, Episode)]

    for operation in ("read", "create", "patch"):
        assert not SCHEDULE_WRITABLE_FIELDS & set(stock_schema[operation]["properties"])
        for schema in opted_in_schemas:
            assert SCHEDULE_WRITABLE_FIELDS <= set(schema[operation]["properties"])


@pytest.mark.parametrize("fixture_name", ["post", "episode"])
def test_revision_bound_publish_schedules_selected_future_revision(client, admin_user, request, fixture_name) -> None:
    page = request.getfixturevalue(fixture_name)
    token = _bearer_token(admin_user)
    base_revision = _unpublished_base_revision(page, admin_user)
    go_live_at = datetime(2099, 1, 2, 3, 4, tzinfo=timezone.utc)

    update = _adapter_update(client, token, page, base_revision.pk, {"go_live_at": go_live_at.isoformat()})
    assert update.status_code == 200
    selected_id = update.json()["latest_revision_id"]
    response = _adapter_publish(client, token, page, f'"{selected_id}"')

    assert response.status_code == 200
    assert response.json() == {
        "id": page.pk,
        "meta": {"type": page._meta.label},
        "revision_id": selected_id,
        "live": False,
        "live_revision_id": None,
    }
    page.refresh_from_db()
    assert page.live is False
    assert page.live_revision_id is None
    assert page.go_live_at == go_live_at
    assert Revision.objects.get(pk=selected_id).approved_go_live_at == go_live_at
    assert isinstance(Page.objects.get(pk=page.pk).specific.get_lock(), ScheduledForPublishLock)
    listed = client.get(
        reverse("wagtailapi_v3:list_page_revisions", kwargs={"page_id": page.pk}),
        {"approved_go_live_at_from": go_live_at.isoformat()},
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert listed.status_code == 200
    assert [(item["id"], item["approved_go_live_at"]) for item in listed.json()["items"]] == [
        (selected_id, "2099-01-02T03:04:00Z")
    ]


def test_revision_bound_publish_with_past_go_live_at_publishes_now(client, admin_user, post) -> None:
    token = _bearer_token(admin_user)
    base_revision = _unpublished_base_revision(post, admin_user)
    go_live_at = django_timezone.now() - timedelta(days=1)

    update = _adapter_update(client, token, post, base_revision.pk, {"go_live_at": go_live_at.isoformat()})
    assert update.status_code == 200
    selected_id = update.json()["latest_revision_id"]
    response = _adapter_publish(client, token, post, f'"{selected_id}"')

    assert response.status_code == 200
    assert response.json()["live"] is True
    post.refresh_from_db()
    assert post.live_revision_id == selected_id
    assert Revision.objects.get(pk=selected_id).approved_go_live_at is None


def test_scheduled_audio_less_episode_is_rejected_before_approval(client, admin_user, podcast, body) -> None:
    episode = _draft_episode(podcast, body, slug="v3-scheduled-audio-less")
    token = _bearer_token(admin_user)
    base_revision = episode.save_revision(user=admin_user)
    update = _adapter_update(client, token, episode, base_revision.pk, {"go_live_at": "2099-01-02T03:04:00Z"})
    assert update.status_code == 200
    selected_id = update.json()["latest_revision_id"]

    response = _adapter_publish(client, token, episode, f'"{selected_id}"')

    _assert_audio_required(response)
    episode.refresh_from_db()
    assert episode.live is False
    assert not episode.revisions.filter(approved_go_live_at__isnull=False).exists()
    assert not PageLogEntry.objects.filter(page_id=episode.pk, action="wagtail.publish.schedule").exists()


def test_schedule_input_rejects_expiry_before_go_live_in_one_request(client, admin_user, post) -> None:
    base_revision = _unpublished_base_revision(post, admin_user)

    response = _adapter_update(
        client,
        _bearer_token(admin_user),
        post,
        base_revision.pk,
        {"go_live_at": "2099-01-03T00:00:00Z", "expire_at": "2099-01-02T00:00:00Z"},
    )

    assert response.status_code == 422
    assert {tuple(error["loc"]) for error in response.json()["errors"]} == {("go_live_at",), ("expire_at",)}
    post.refresh_from_db()
    assert post.latest_revision_id == base_revision.pk


def test_partial_schedule_input_skips_cross_field_validation(client, admin_user, post) -> None:
    token = _bearer_token(admin_user)
    base_revision = _unpublished_base_revision(post, admin_user)
    expiring = _adapter_update(client, token, post, base_revision.pk, {"expire_at": "2099-01-02T00:00:00Z"})
    assert expiring.status_code == 200

    response = _adapter_update(
        client, token, post, expiring.json()["latest_revision_id"], {"go_live_at": "2099-01-03T00:00:00Z"}
    )

    assert response.status_code == 200
    draft = Revision.objects.get(pk=response.json()["latest_revision_id"]).as_object()
    assert draft.go_live_at > draft.expire_at


def _preview(client, page: Post, token: str | None) -> Any:
    headers = {} if token is None else {"HTTP_AUTHORIZATION": f"Bearer {token}"}
    return client.get(reverse("wagtailapi_v3:cast_draft_preview", kwargs={"page_id": page.pk}), **headers)


@pytest.mark.parametrize("fixture_name", ["post", "episode"])
@pytest.mark.parametrize("version", ["live", "draft"])
@pytest.mark.parametrize("authenticated", [False, True])
def test_stock_cast_page_detail_read_fails_response_serialization(
    client, admin_user, request, fixture_name, version, authenticated
) -> None:
    page = request.getfixturevalue(fixture_name)
    headers = {"HTTP_AUTHORIZATION": f"Bearer {_bearer_token(admin_user)}"} if authenticated else {}

    response = client.get(
        reverse("wagtailapi_v3:detail_page", kwargs={"page_id": page.pk}), {"version": version}, **headers
    )

    _assert_cast_write_response_failure(response, type(page))


def test_stock_draft_read_requires_explore_not_edit_permission(client, admin_user, site, blog) -> None:
    other_blog = BlogFactory(owner=admin_user, parent=site.root_page, title="Other blog", slug="other-blog")
    live_title = blog.title
    draft = blog.get_latest_revision_as_object()
    draft.title = "Draft blog title"
    draft.save_revision(user=admin_user)
    publisher = _page_permission_user(blog, "publish_page")
    url = reverse("wagtailapi_v3:detail_page", kwargs={"page_id": blog.pk})

    publisher_read = client.get(url, {"version": "draft"}, HTTP_AUTHORIZATION=f"Bearer {_bearer_token(publisher)}")
    anonymous_read = client.get(url, {"version": "draft"})
    outsider = _page_permission_user(other_blog, "change_page")
    outsider_read = client.get(url, {"version": "draft"}, HTTP_AUTHORIZATION=f"Bearer {_bearer_token(outsider)}")

    assert blog.permissions_for_user(publisher).can_edit() is False
    assert publisher_read.status_code == 200
    assert publisher_read.json()["title"] == "Draft blog title"
    assert anonymous_read.status_code == 200
    assert anonymous_read.json()["title"] == live_title
    assert outsider_read.status_code == 404


STOCK_V3_PAGE_ROUTE_NAMES = {
    "list_pages",
    "create_page",
    "find_page",
    "detail_page",
    "update_page",
    "delete_page",
    "list_page_revisions",
    "detail_page_revision",
    "pages_actions_publish",
    "pages_actions_unpublish",
    "pages_actions_copy",
    "pages_actions_move",
    "pages_actions_delete",
    "pages_actions_revert",
    "pages_actions_convert_alias",
    "pages_actions_create_alias",
    "pages_actions_copy_for_translation",
}


def test_stock_v3_page_routes_have_no_rendered_preview() -> None:
    from wagtail.api.v3.urls import api

    page_routes = {pattern.name for pattern in api.urls[0] if "page" in pattern.name}
    adapter_names = {"cast_revision_update", "cast_revision_publish", "cast_draft_preview"}

    # The complete stock page-route inventory; none of these renders HTML.
    assert page_routes - adapter_names == STOCK_V3_PAGE_ROUTE_NAMES


@pytest.mark.parametrize("fixture_name", ["post", "episode"])
def test_adapter_preview_renders_latest_draft(client, admin_user, request, fixture_name) -> None:
    page = request.getfixturevalue(fixture_name)
    draft = page.get_latest_revision_as_object()
    draft.title = "Unpublished preview title"
    draft.save_revision(user=admin_user)

    response = _preview(client, page, _bearer_token(admin_user))

    assert response.status_code == 200
    assert response["Content-Type"] == "text/html; charset=utf-8"
    assert "Unpublished preview title" in response.content.decode()
    page.refresh_from_db()
    assert page.title != "Unpublished preview title"


def test_adapter_preview_enforces_authentication_and_edit_permission(client, admin_user, site, blog, post) -> None:
    other_blog = BlogFactory(owner=admin_user, parent=site.root_page, title="Other blog", slug="other-blog")
    draft = post.get_latest_revision_as_object()
    draft.title = "Secret preview title"
    draft.save_revision(user=admin_user)
    session_client = Client()
    session_client.force_login(admin_user)

    session_only = _preview(session_client, post, None)
    publisher = _preview(client, post, _bearer_token(_page_permission_user(blog, "publish_page")))
    outsider = _preview(client, post, _bearer_token(_page_permission_user(other_blog, "change_page")))
    editor = _preview(client, post, _bearer_token(_page_permission_user(blog, "change_page")))

    assert session_only.status_code == 401
    assert publisher.status_code == 403
    assert outsider.status_code == 403
    for denied in (session_only, publisher, outsider):
        assert "Secret preview title" not in denied.content.decode()
    assert editor.status_code == 200
    assert "Secret preview title" in editor.content.decode()


def test_adapter_preview_renders_with_session_identity_not_bearer(client, admin_user, blog, post, mocker) -> None:
    spy = mocker.spy(Post, "serve_preview")
    token = _bearer_token(_page_permission_user(blog, "change_page"))

    bearer_only = _preview(client, post, token)
    client.force_login(admin_user)
    with_session = _preview(client, post, token)

    assert bearer_only.status_code == with_session.status_code == 200
    rendered_users = [call.args[1].user for call in spy.call_args_list]
    assert rendered_users[0].is_authenticated is False
    assert rendered_users[1] == admin_user


def test_adapter_preview_synchronizes_draft_media_relationships(client, admin_user, post_with_image) -> None:
    image = post_with_image.images.get()
    post_with_image.images.remove(image)

    response = _preview(client, post_with_image, _bearer_token(admin_user))

    assert response.status_code == 200
    assert post_with_image.revisions.count() == 0
    assert list(Post.objects.get(pk=post_with_image.pk).images.all()) == [image]


def test_adapter_preview_reports_missing_page(client, admin_user) -> None:
    response = client.get(
        reverse("wagtailapi_v3:cast_draft_preview", kwargs={"page_id": 999_999}),
        HTTP_AUTHORIZATION=f"Bearer {_bearer_token(admin_user)}",
    )

    assert response.status_code == 404


def _body_update(client, token: str, page: Post, base_revision_id: int, values: dict) -> Any:
    return client.patch(
        reverse("wagtailapi_v3:cast_body_update", kwargs={"page_id": page.pk}),
        values,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
        HTTP_IF_MATCH=f'"{base_revision_id}"',
    )


def _stock_body_update(client, token: str, page: Post, body: list) -> Any:
    return client.patch(
        reverse("wagtailapi_v3:update_page", kwargs={"page_id": page.pk}),
        {"body": body},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )


def _grant_image_choice(user: AbstractUser) -> None:
    group = Group.objects.create(name=f"v3 image choosers {user.pk}")
    permission = Permission.objects.get(codename="choose_image", content_type__app_label="wagtailimages")
    GroupCollectionPermission.objects.create(
        group=group, collection=Collection.get_first_root_node(), permission=permission
    )
    user.groups.add(group)


def _section_types(page: Post) -> list[str]:
    return [section["type"] for section in page.get_latest_revision_as_object().body.raw_data]


def test_stock_body_schema_has_no_block_guidance(client, admin_user) -> None:
    schema = _schema(client, _bearer_token(admin_user), Post)

    assert schema["patch"]["properties"]["body"] == {"default": [], "items": {}, "title": "Body", "type": "array"}


def test_stock_body_write_replaces_whole_field_and_sanitizes_rich_text(client, admin_user, post) -> None:
    assert _section_types(post) == ["overview", "detail"]
    unsafe = '<p>Kept<script>alert(1)</script><a href="javascript:run()">link</a><img src="x" onerror="run()"></p>'

    response = _stock_body_update(
        client,
        _bearer_token(admin_user),
        post,
        [{"type": "overview", "value": [{"type": "paragraph", "value": unsafe}]}],
    )

    _assert_cast_write_response_failure(response, Post)
    post.refresh_from_db()
    assert _section_types(post) == ["overview"]
    paragraph = post.get_latest_revision_as_object().body.raw_data[0]["value"][0]["value"]
    assert "Kept" in paragraph
    for fragment in ("<script", "javascript:", "onerror", "<img"):
        assert fragment not in paragraph


def test_stock_body_write_accepts_unchoosable_image_and_nulls_missing_image(client, blog, post, image) -> None:
    user = _page_permission_user(blog, "change_page")
    assert get_image_model().objects.filter(pk=image.pk).exists()
    assert get_choosable_image(image.pk, user) is None
    missing_image_id = image.pk + 1000

    response = _stock_body_update(
        client,
        _bearer_token(user),
        post,
        [
            {
                "type": "overview",
                "value": [{"type": "image", "value": image.pk}, {"type": "image", "value": missing_image_id}],
            }
        ],
    )

    _assert_cast_write_response_failure(response, Post)
    post.refresh_from_db()
    blocks = post.get_latest_revision_as_object().body.raw_data[0]["value"]
    assert [(block["type"], block["value"]) for block in blocks] == [
        ("image", image.pk),
        ("image", None),
    ]


def test_stock_body_write_rejects_unknown_block_without_revision(client, admin_user, post) -> None:
    revision_count = post.revisions.count()

    response = _stock_body_update(
        client, _bearer_token(admin_user), post, [{"type": "overview", "value": [{"type": "unknown", "value": 1}]}]
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Validation failed"
    assert post.revisions.count() == revision_count


@pytest.mark.parametrize("fixture_name", ["post", "episode"])
def test_body_adapter_converts_author_blocks_and_preserves_other_section(
    client, admin_user, request, fixture_name, image
) -> None:
    page = request.getfixturevalue(fixture_name)
    _grant_image_choice(admin_user)
    assert get_choosable_image(image.pk, admin_user) == image
    base_revision = page.get_latest_revision_as_object().save_revision(user=admin_user)
    detail_before = base_revision.as_object().body.raw_data[1]

    response = _body_update(
        client,
        _bearer_token(admin_user),
        page,
        base_revision.pk,
        {
            "overview": [
                {"type": "paragraph", "value": "<p>Adapter overview</p>"},
                {"type": "image", "value": {"id": image.pk}},
            ]
        },
    )

    assert response.status_code == 200
    page.refresh_from_db()
    assert page.latest_revision_id == response.json()["latest_revision_id"]
    sections = page.get_latest_revision_as_object().body.raw_data
    assert [section["type"] for section in sections] == ["overview", "detail"]
    assert [(block["type"], block["value"]) for block in sections[0]["value"]] == [
        ("paragraph", "<p>Adapter overview</p>"),
        ("image", image.pk),
    ]
    assert sections[1] == detail_before


def test_body_adapter_rejects_unchoosable_image_without_revision(client, admin_user, blog, post, image) -> None:
    base_revision = post.get_latest_revision_as_object().save_revision(user=admin_user)
    user = _page_permission_user(blog, "change_page")
    assert get_choosable_image(image.pk, user) is None

    response = _body_update(
        client,
        _bearer_token(user),
        post,
        base_revision.pk,
        {"detail": [{"type": "image", "value": {"id": image.pk}}]},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert [error["code"] for error in response.json()["errors"]["detail.0.value.id"]] == ["not_found"]
    post.refresh_from_db()
    assert post.latest_revision_id == base_revision.pk


def test_body_adapter_rejects_unsupported_author_block(client, admin_user, post) -> None:
    base_revision = post.get_latest_revision_as_object().save_revision(user=admin_user)

    response = _body_update(
        client, _bearer_token(admin_user), post, base_revision.pk, {"overview": [{"type": "unknown", "value": 1}]}
    )

    assert response.status_code == 422
    assert set(response.json()["errors"]) == {"overview.0.type"}
    post.refresh_from_db()
    assert post.latest_revision_id == base_revision.pk


def test_body_adapter_preconditions(client, admin_user, site, post, body) -> None:
    other_blog = BlogFactory(owner=admin_user, parent=site.root_page, title="Other blog", slug="other-blog")
    stale = post.get_latest_revision_as_object().save_revision(user=admin_user)
    current = post.get_latest_revision_as_object().save_revision(user=admin_user)
    token = _bearer_token(admin_user)
    overview = {"overview": [{"type": "paragraph", "value": "<p>Ignored</p>"}]}

    empty = _body_update(client, token, post, current.pk, {})
    conflict = _body_update(client, token, post, stale.pk, overview)
    outsider_token = _bearer_token(_page_permission_user(other_blog, "change_page"))
    outsider = _body_update(client, outsider_token, post, stale.pk, overview)
    unquoted = client.patch(
        reverse("wagtailapi_v3:cast_body_update", kwargs={"page_id": post.pk}),
        overview,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
        HTTP_IF_MATCH=str(current.pk),
    )

    assert empty.status_code == 400
    assert empty.json()["code"] == "empty_body_update"
    assert conflict.status_code == 409
    assert conflict.json()["current_revision_id"] == current.pk
    assert outsider.status_code == 403
    assert str(current.pk) not in outsider.content.decode()
    assert unquoted.status_code == 400
    assert unquoted.json()["code"] == "invalid_base_revision"
    post.refresh_from_db()
    assert post.latest_revision_id == current.pk


def _grant_collection_permissions(user: AbstractUser, collections: list[Collection], *codenames: str) -> None:
    group = Group.objects.create(name=f"v3 image collections {user.pk} {len(user.groups.all())}")
    for collection in collections:
        for codename in codenames:
            permission = Permission.objects.get(codename=codename, content_type__app_label="wagtailimages")
            GroupCollectionPermission.objects.create(group=group, collection=collection, permission=permission)
    user.groups.add(group)


def _child_collections(*names: str) -> list[Collection]:
    children = []
    for name in names:
        root = Collection.get_first_root_node()
        children.append(root.add_child(name=name))
    return children


def _upload_image(client, token: str, collection: Collection | None, content: bytes | None = None) -> Any:
    data = {"file": SimpleUploadedFile("upload.png", content or create_1_px_image(), content_type="image/png")}
    data["title"] = "v3 upload"
    if collection is not None:
        data["collection_id"] = collection.pk
    return client.post(reverse("wagtailapi_v3:create_image"), data, HTTP_AUTHORIZATION=f"Bearer {token}")


def test_stock_v3_exposes_images_and_documents_but_no_cast_media(client, admin_user) -> None:
    from wagtail.api.v3.urls import api

    listed = client.get(
        reverse("wagtailapi_v3:list_schemas"), HTTP_AUTHORIZATION=f"Bearer {_bearer_token(admin_user)}"
    )
    types = {entry["name"] for entry in listed.json()["types"]}
    route_names = {pattern.name for pattern in api.urls[0]}

    assert {"wagtailimages.Image", "wagtaildocs.Document"} <= types
    assert not {"cast.Audio", "cast.Video", "cast.Transcript"} & types
    assert {"create_image", "create_document"} <= route_names
    assert not {name for name in route_names if any(kind in name for kind in ("audio", "video", "transcript"))}


def test_stock_image_upload_scopes_collections_and_validates_files(client) -> None:
    allowed, forbidden, other_allowed = _child_collections("Allowed", "Forbidden", "Other allowed")
    user = UserFactory(is_staff=False)
    _grant_collection_permissions(user, [allowed, other_allowed], "add_image")
    token = _bearer_token(user)

    denied = _upload_image(client, token, forbidden)
    missing = _upload_image(client, token, None)
    invalid = _upload_image(client, token, allowed, b"not an image")
    created = _upload_image(client, token, other_allowed)

    for response, field in ((denied, "collection"), (missing, "collection"), (invalid, "file")):
        assert response.status_code == 422
        assert [error["loc"] for error in response.json()["errors"]] == [[field]]
    assert created.status_code == 201
    image = get_image_model().objects.get()
    assert created.json()["id"] == image.pk
    assert image.collection == other_allowed
    assert image.uploaded_by_user == user


def test_stock_image_upload_replaces_request_collection_when_one_is_usable(client) -> None:
    allowed, forbidden = _child_collections("Only allowed", "Requested")
    user = UserFactory(is_staff=False)
    _grant_collection_permissions(user, [allowed], "add_image")

    response = _upload_image(client, _bearer_token(user), forbidden)

    assert response.status_code == 201
    assert get_image_model().objects.get().collection == allowed


def test_stock_image_upload_does_not_require_choose_permission(client, admin_user, blog, post) -> None:
    (collection,) = _child_collections("Add only")
    user = _page_permission_user(blog, "change_page")
    _grant_collection_permissions(user, [collection], "add_image")
    token = _bearer_token(user)
    base_revision = post.get_latest_revision_as_object().save_revision(user=admin_user)

    upload = _upload_image(client, token, collection)
    image = get_image_model().objects.get()
    attach = _body_update(
        client, token, post, base_revision.pk, {"overview": [{"type": "image", "value": {"id": image.pk}}]}
    )

    assert upload.status_code == 201
    assert get_choosable_image(image.pk, user) is None
    assert attach.status_code == 422
    assert [error["code"] for error in attach.json()["errors"]["overview.0.value.id"]] == ["not_found"]


def test_anonymous_image_listing_matches_cast_v2_exposure(client, image) -> None:
    v3 = client.get(reverse("wagtailapi_v3:list_images"))
    v2 = client.get(reverse("cast:api:wagtail:images:listing"))

    assert v3.status_code == v2.status_code == 200
    assert [item["id"] for item in v3.json()["items"]] == [image.pk]
    assert [item["id"] for item in v2.json()["items"]] == [image.pk]


postgres_only = pytest.mark.skipif(connection.vendor != "postgresql", reason="PostgreSQL row-lock semantics")


@pytest.fixture()
def restored_wagtail_roots(transactional_db) -> None:
    """Recreate the roots that a previous transactional test's flush removed."""
    locale, _created = Locale.objects.get_or_create(language_code=settings.LANGUAGE_CODE)
    if Page.get_first_root_node() is None:
        Page.add_root(instance=Page(title="Root", slug="root", locale=locale))
    if Collection.get_first_root_node() is None:
        Collection.add_root(instance=Collection(name="Root"))


@pytest.fixture()
def pg_actors(restored_wagtail_roots, request) -> tuple[AbstractUser, Post]:
    """Request user and page fixtures only after the roots exist again."""
    return request.getfixturevalue("admin_user"), request.getfixturevalue("post")


class _Pause:
    """Pause one adapter call after its locks are held, then delegate."""

    def __init__(self, target: Any, *, calls: int = 1) -> None:
        self.target = target
        self.remaining = calls
        self.reached = threading.Event()
        self.release = threading.Event()

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if self.remaining:
            self.remaining -= 1
            self.reached.set()
            assert self.release.wait(timeout=5)
        return self.target(*args, **kwargs)


def _in_thread(errors: list, work: Any, *, finished: threading.Event | None = None) -> threading.Thread:
    def run() -> None:
        close_old_connections()
        try:
            work()
            if finished is not None:
                finished.set()
        except Exception as exc:  # pragma: no cover - surfaced by the caller's assertion
            errors.append(exc)
        finally:
            close_old_connections()

    thread = threading.Thread(target=run)
    thread.start()
    return thread


def _wait_for_lock_waiter() -> None:
    """Wait until another backend in this database is blocked on a lock."""
    deadline = time.monotonic() + 5
    with connection.cursor() as cursor:
        while time.monotonic() < deadline:
            cursor.execute(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database() AND wait_event_type = 'Lock' AND pid <> pg_backend_pid()"
            )
            if cursor.fetchone()[0]:
                return
            time.sleep(0.02)
    raise AssertionError("the competing writer never waited on a PostgreSQL lock")


def _assert_blocked_until_release(pause: _Pause, finished: threading.Event, threads: list, errors: list) -> None:
    try:
        _wait_for_lock_waiter()
        assert not finished.is_set()
    finally:
        pause.release.set()
        for thread in threads:
            thread.join(timeout=10)
    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    assert finished.is_set()


@postgres_only
@pytest.mark.django_db(transaction=True)
def test_postgres_revision_bound_publish_serializes_with_new_draft(pg_actors, monkeypatch) -> None:
    from tests import wagtail_v3_adapter

    admin_user, post = pg_actors
    token = _bearer_token(admin_user)
    selected = _save_cover_revision(post, admin_user, "Reviewed draft")
    registry = wagtail_v3_adapter.action_registry
    pause = _Pause(registry.get_action_class)
    monkeypatch.setattr(wagtail_v3_adapter, "action_registry", type("Registry", (), {"get_action_class": pause})())
    errors: list = []
    responses: list = []
    newer: list = []
    finished = threading.Event()

    def publish() -> None:
        responses.append(_adapter_publish(Client(), token, post, f'"{selected.pk}"'))

    def save_newer_draft() -> None:
        assert pause.reached.wait(timeout=5)
        page = Post.objects.get(pk=post.pk)
        newer.append(_save_cover_revision(page, admin_user, "Concurrent draft"))

    threads = [_in_thread(errors, publish)]
    assert pause.reached.wait(timeout=5)
    threads.append(_in_thread(errors, save_newer_draft, finished=finished))
    _assert_blocked_until_release(pause, finished, threads, errors)

    assert responses[0].status_code == 200
    assert responses[0].json()["live_revision_id"] == selected.pk
    post.refresh_from_db()
    assert post.live_revision_id == selected.pk
    assert post.cover_alt_text == "Reviewed draft"
    assert post.latest_revision_id == newer[0].pk
    assert post.has_unpublished_changes is True


@postgres_only
@pytest.mark.django_db(transaction=True)
def test_postgres_draft_only_update_serializes_with_schedule_approval(pg_actors, monkeypatch) -> None:
    from tests import wagtail_v3_adapter

    admin_user, post = pg_actors
    token = _bearer_token(admin_user)
    base_revision = _unpublished_base_revision(post, admin_user)
    pause = _Pause(wagtail_v3_adapter.build_page_update_form)
    monkeypatch.setattr(wagtail_v3_adapter, "build_page_update_form", pause)
    errors: list = []
    responses: list = []
    finished = threading.Event()

    def update() -> None:
        responses.append(
            _adapter_update(
                Client(), token, post, base_revision.pk, {"cover_alt_text": "Serialized"}, require_unpublished=True
            )
        )

    def approve_base_revision() -> None:
        assert pause.reached.wait(timeout=5)
        with transaction.atomic():
            Revision.objects.filter(pk=base_revision.pk).update(
                approved_go_live_at=django_timezone.now() + timedelta(days=1)
            )

    threads = [_in_thread(errors, update)]
    assert pause.reached.wait(timeout=5)
    threads.append(_in_thread(errors, approve_base_revision, finished=finished))
    _assert_blocked_until_release(pause, finished, threads, errors)

    assert responses[0].status_code == 200
    base_revision.refresh_from_db()
    assert base_revision.approved_go_live_at is not None


@postgres_only
@pytest.mark.django_db(transaction=True)
def test_postgres_concurrent_updates_from_same_base_conflict(pg_actors, monkeypatch) -> None:
    from tests import wagtail_v3_adapter

    admin_user, post = pg_actors
    token = _bearer_token(admin_user)
    base_revision = post.get_latest_revision_as_object().save_revision(user=admin_user)
    pause = _Pause(wagtail_v3_adapter.build_page_update_form)
    monkeypatch.setattr(wagtail_v3_adapter, "build_page_update_form", pause)
    errors: list = []
    first: list = []
    second: list = []
    finished = threading.Event()

    def update(results: list, value: str) -> Any:
        return lambda: results.append(
            _adapter_update(Client(), token, post, base_revision.pk, {"cover_alt_text": value})
        )

    threads = [_in_thread(errors, update(first, "First writer"))]
    assert pause.reached.wait(timeout=5)
    threads.append(_in_thread(errors, update(second, "Second writer"), finished=finished))
    _assert_blocked_until_release(pause, finished, threads, errors)

    assert first[0].status_code == 200
    assert second[0].status_code == 409
    assert second[0].json()["current_revision_id"] == first[0].json()["latest_revision_id"]
    post.refresh_from_db()
    assert post.latest_revision_id == first[0].json()["latest_revision_id"]
    assert post.get_latest_revision_as_object().cover_alt_text == "First writer"
