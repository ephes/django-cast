"""Wagtail 8 v3 discovery, authentication, exposure, and draft-write experiment."""

from datetime import datetime, timezone

import pytest
from django.conf import settings
from django.urls import NoReverseMatch, reverse
from django.urls.base import clear_url_caches
from wagtail import VERSION as WAGTAIL_VERSION
from wagtail.models import Revision

if (
    WAGTAIL_VERSION < (8, 0)
    or "wagtail.api.v3" not in settings.INSTALLED_APPS
    or settings.ROOT_URLCONF != "tests.wagtail_v3_urls"
):
    pytest.skip("Wagtail v3 experiment settings are not active", allow_module_level=True)

from wagtail.models import APIToken  # noqa: E402

from cast.models import Episode, Post  # noqa: E402
from tests.wagtail_v3_writable import (  # noqa: E402
    EPISODE_ONLY_WRITABLE_FIELDS,
    POST_WRITABLE_FIELDS,
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
WRITABLE_FIELDS = {
    Post: POST_WRITABLE_FIELDS,
    Episode: POST_WRITABLE_FIELDS | EPISODE_ONLY_WRITABLE_FIELDS,
}


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


def _adapter_update(client, token: str, page: Post, base_revision_id: int, values: dict) -> object:
    return client.patch(
        reverse("wagtailapi_v3:cast_revision_update", kwargs={"page_id": page.pk}),
        values,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
        HTTP_IF_MATCH=f'"{base_revision_id}"',
    )


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
