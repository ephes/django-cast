"""Wagtail 8 v3 mounting, discovery, authentication, and exposure baseline."""

import pytest
from django.conf import settings
from django.urls import NoReverseMatch, reverse
from django.urls.base import clear_url_caches
from wagtail import VERSION as WAGTAIL_VERSION

if (
    WAGTAIL_VERSION < (8, 0)
    or "wagtail.api.v3" not in settings.INSTALLED_APPS
    or settings.ROOT_URLCONF != "tests.wagtail_v3_urls"
):
    pytest.skip("Wagtail v3 experiment settings are not active", allow_module_level=True)

from wagtail.models import APIToken  # noqa: E402

from cast.models import Episode, Post  # noqa: E402

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
    """Pin the prerequisite inventory; the next writable-field slice must update these assertions."""
    schema = _schema(client, _bearer_token(admin_user), model)
    read_fields = set(schema["read"]["properties"])
    create_fields = set(schema["create"]["properties"])
    patch_fields = set(schema["patch"]["properties"])

    assert COMMON_PAGE_FIELDS <= create_fields
    assert COMMON_PAGE_FIELDS <= patch_fields
    assert read_cast_fields <= read_fields
    assert (intended_fields - COMMON_PAGE_FIELDS).isdisjoint(create_fields)
    assert (intended_fields - COMMON_PAGE_FIELDS).isdisjoint(patch_fields)
    if model is Episode:
        assert (EPISODE_FIELDS - POST_FIELDS).isdisjoint(read_fields)


@pytest.mark.parametrize("fixture_name", ["post", "episode"])
def test_public_page_listing_exposes_live_cast_page_type(client, request, fixture_name) -> None:
    page = request.getfixturevalue(fixture_name)
    assert page.live is True
    response = client.get(reverse("wagtailapi_v3:list_pages"), {"type": page._meta.label})

    assert response.status_code == 200
    exposed = {(item["id"], item["meta"]["type"]) for item in response.json()["items"]}
    assert (page.id, page._meta.label) in exposed
