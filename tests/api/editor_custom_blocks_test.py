import pytest
from django.test import override_settings
from django.urls import reverse


WEEKNOTE_LINK = {
    "category": "articles",
    "kind": "article",
    "title": "Example article",
    "url": "https://example.com/article",
    "source": "Example",
    "source_url": "",
    "description": "<p>Short summary.</p>",
}


CUSTOM_BLOCK_SETTINGS = {
    "overview": ["tests.custom_post_body_blocks.weeknote_links_block"],
    "detail": ["tests.custom_post_body_blocks.detail_weeknote_links_block"],
}


@pytest.mark.django_db
@override_settings(CAST_POST_BODY_BLOCKS=CUSTOM_BLOCK_SETTINGS)
def test_editor_post_create_reads_custom_overview_block_without_internal_wrappers(api_client, blog, admin_user):
    api_client.force_authenticate(user=admin_user)
    create_url = reverse("cast:api:editor_post_create")
    payload = {
        "parent": {"id": blog.id},
        "title": "Custom overview",
        "slug": "custom-overview",
        "overview": [{"type": "weeknote_links", "value": [WEEKNOTE_LINK]}],
    }

    response = api_client.post(create_url, payload, format="json")

    assert response.status_code == 201, response.content
    data = response.json()
    assert data["overview"] == [{"type": "weeknote_links", "value": [WEEKNOTE_LINK]}]


@pytest.mark.django_db
@override_settings(CAST_POST_BODY_BLOCKS=CUSTOM_BLOCK_SETTINGS)
def test_editor_post_patch_reads_custom_detail_block_without_internal_wrappers(api_client, blog, admin_user):
    api_client.force_authenticate(user=admin_user)
    create_url = reverse("cast:api:editor_post_create")
    created = api_client.post(
        create_url,
        {
            "parent": {"id": blog.id},
            "title": "Custom detail",
            "slug": "custom-detail",
            "overview": [],
        },
        format="json",
    ).json()
    detail_url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})
    detail = [{"type": "weeknote_links", "value": [WEEKNOTE_LINK]}]

    response = api_client.patch(
        detail_url,
        {"base_revision_id": created["latest_revision_id"], "detail": detail},
        format="json",
    )

    assert response.status_code == 200, response.content
    assert response.json()["detail"] == detail
    assert api_client.get(detail_url, format="json").json()["detail"] == detail


@pytest.mark.django_db
@override_settings(CAST_POST_BODY_BLOCKS=CUSTOM_BLOCK_SETTINGS)
def test_editor_episode_create_reads_custom_overview_block_without_internal_wrappers(api_client, podcast, admin_user):
    api_client.force_authenticate(user=admin_user)
    create_url = reverse("cast:api:editor_episode_create")
    payload = {
        "parent": {"id": podcast.id},
        "title": "Custom episode",
        "slug": "custom-episode",
        "overview": [{"type": "weeknote_links", "value": [WEEKNOTE_LINK]}],
    }

    response = api_client.post(create_url, payload, format="json")

    assert response.status_code == 201, response.content
    data = response.json()
    assert data["type"] == "cast.Episode"
    assert data["overview"] == [{"type": "weeknote_links", "value": [WEEKNOTE_LINK]}]


@pytest.mark.django_db
@override_settings(CAST_POST_BODY_BLOCKS=CUSTOM_BLOCK_SETTINGS)
@pytest.mark.parametrize("kind", ["post", "episode"])
def test_custom_rich_text_is_sanitized_on_create_and_patch(api_client, blog, podcast, admin_user, kind):
    api_client.force_authenticate(user=admin_user)
    parent = blog if kind == "post" else podcast
    link = {**WEEKNOTE_LINK, "description": '<p onclick="alert(1)">Safe</p>'}
    value = [{"type": "weeknote_links", "value": [link]}]
    response = api_client.post(
        reverse(f"cast:api:editor_{kind}_create"),
        {"parent": {"id": parent.pk}, "title": "Safe custom text", "overview": value, "detail": value},
        format="json",
    )
    assert response.status_code == 201, response.content
    created = response.json()
    for section in ("overview", "detail"):
        assert created[section][0]["value"][0]["description"] == "<p>Safe</p>"
    detail_url = reverse(f"cast:api:editor_{kind}_detail", kwargs={"pk": created["id"]})
    response = api_client.patch(
        detail_url,
        {"base_revision_id": created["latest_revision_id"], "overview": value, "detail": value},
        format="json",
    )
    assert response.status_code == 200, response.content
    for section in ("overview", "detail"):
        assert api_client.get(detail_url).json()[section][0]["value"][0]["description"] == "<p>Safe</p>"


@pytest.mark.django_db
@override_settings(CAST_POST_BODY_BLOCKS=CUSTOM_BLOCK_SETTINGS)
def test_custom_rich_text_conversion_errors_keep_nested_paths(api_client, blog, admin_user):
    api_client.force_authenticate(user=admin_user)
    link = {**WEEKNOTE_LINK, "description": "<p><b><i>Unbalanced</b></i></p>"}
    response = api_client.post(
        reverse("cast:api:editor_post_create"),
        {
            "parent": {"id": blog.pk},
            "title": "Invalid custom text",
            "overview": [
                {"type": "paragraph", "value": 123},
                {"type": "weeknote_links", "value": [link]},
                {"type": "paragraph", "value": False},
            ],
        },
        format="json",
    )
    assert response.status_code == 400, response.content
    assert response.json()["errors"] == {
        "overview.0.value": [{"code": "invalid", "message": "Expected a string value."}],
        "overview.1.value.0.description": [{"code": "invalid", "message": "Invalid rich text."}],
        "overview.2.value": [{"code": "invalid", "message": "Expected a string value."}],
    }
