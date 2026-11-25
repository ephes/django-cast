from uuid import UUID

import pytest
from django.urls import reverse

from cast.models import Post
from tests.api.editor_posts_helpers import (
    grant_collection_permission,
    grant_wagtail_admin_access,
    page_permission_user,
)


@pytest.mark.django_db
def test_gallery_captions_survive_editor_create_get_and_patch(api_client, blog, admin_user, image):
    grant_collection_permission(admin_user, image.collection, app_label="wagtailimages", codename="choose_image")
    api_client.force_authenticate(user=admin_user)
    overview = [
        {"type": "gallery", "value": [{"id": image.pk, "caption": "First"}, {"id": image.pk, "caption": "Second"}]}
    ]
    response = api_client.post(
        reverse("cast:api:editor_post_create"),
        {"parent": {"id": blog.pk}, "title": "Gallery", "slug": "gallery", "overview": overview},
        format="json",
    )
    assert response.status_code == 201, response.json()
    created = response.json()
    url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})

    def stored_items():
        draft = Post.objects.get(pk=created["id"]).get_latest_revision_as_object()
        return draft.body.raw_data[0]["value"][0]["value"]["gallery"]

    before = api_client.get(url).json()
    gallery = before["overview"][0]
    first, second = gallery["value"]
    first_id, second_id = (item["id"] for item in stored_items())
    assert first == {"id": image.pk, "caption": "First", "existing_item_id": first_id}
    assert second == {"id": image.pk, "caption": "Second", "existing_item_id": second_id}

    first["caption"] = "Changed"
    gallery["value"] = [second, first, {"id": image.pk, "caption": "New"}]
    updated = api_client.patch(
        url, {"base_revision_id": before["latest_revision_id"], "overview": [gallery]}, format="json"
    )
    assert updated.status_code == 200, updated.json()
    items = stored_items()
    new_id = items[2]["id"]
    assert str(UUID(new_id)) == new_id
    assert new_id not in {first_id, second_id}
    assert [item["id"] for item in items] == [second_id, first_id, new_id]
    gallery["value"][2]["existing_item_id"] = new_id
    assert api_client.get(url).json()["overview"] == [gallery]


@pytest.mark.django_db
def test_editor_captioned_gallery_still_enforces_image_choose_permission(api_client, blog, image):
    user = page_permission_user(codenames=("add_page", "change_page"))
    grant_wagtail_admin_access(user)
    api_client.force_authenticate(user=user)
    response = api_client.post(
        reverse("cast:api:editor_post_create"),
        {
            "parent": {"id": blog.pk},
            "title": "Gallery",
            "slug": "gallery",
            "overview": [{"type": "gallery", "value": [{"id": image.pk, "caption": "Unavailable"}]}],
        },
        format="json",
    )
    assert response.status_code == 400
    assert response.json()["errors"]["overview.0.value.0.id"][0]["code"] == "not_found"
