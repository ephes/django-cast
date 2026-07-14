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
