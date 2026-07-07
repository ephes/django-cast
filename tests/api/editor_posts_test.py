# ruff: noqa: F401,F811,I001
import json
import subprocess

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.models import Group, Permission
from django.urls import reverse
from rest_framework import status
from rest_framework.response import Response
from wagtail.models import Collection, GroupCollectionPermission, GroupPagePermission, Page

from cast import media_probe
from cast.api.editor import media as editor_media
from cast.api.editor.body import (
    SUPPORTED_OVERVIEW_BLOCKS,
    _media_ref_is_available,
    author_blocks_to_overview,
    overview_to_author_blocks,
)
from cast.api.editor.errors import (
    EditorNotFound,
    EditorPermissionDenied,
    EditorValidationError,
    editor_exception_handler,
)
from cast.models import Audio, Episode, Post, Season, Video
from cast.models.snippets import PostCategory

from tests.factories import BlogFactory, EpisodeFactory, PodcastFactory, PostFactory, UserFactory


def grant_wagtail_admin_access(user) -> None:
    permission = Permission.objects.get(codename="access_admin", content_type__app_label="wagtailadmin")
    user.user_permissions.add(permission)


def grant_collection_permission(user, collection, *, app_label: str, codename: str) -> None:
    group = Group.objects.create(name=f"Collection permission {user.pk} {codename} {collection.pk}")
    permission = Permission.objects.get(codename=codename, content_type__app_label=app_label)
    GroupCollectionPermission.objects.create(group=group, collection=collection, permission=permission)
    user.groups.add(group)


def page_permission_user(*, codenames: tuple[str, ...]) -> object:
    user = UserFactory(is_staff=True)
    group = Group.objects.create(name=f"Page permissions {user.pk}")
    root_page = Page.get_first_root_node()
    assert root_page is not None
    for codename in codenames:
        permission = Permission.objects.get(codename=codename, content_type__app_label="wagtailcore")
        GroupPagePermission.objects.create(group=group, page=root_page, permission=permission)
    user.groups.add(group)
    return user


@pytest.fixture
def superuser(django_user_model):
    """A superuser, which passes every Wagtail page and image ``choose`` permission."""
    return django_user_model.objects.create_superuser(
        username="editor-su", email="editor-su@example.com", password="password"
    )


class TestEditorPostDetail:
    pytestmark = pytest.mark.django_db

    def _create(self, api_client, blog, admin_user):
        api_client.force_authenticate(user=admin_user)
        create_url = reverse("cast:api:editor_post_create")
        payload = {
            "parent": {"id": blog.id},
            "title": "Readable draft",
            "slug": "readable-draft",
            "tags": ["weeknotes"],
            "overview": [
                {"type": "paragraph", "value": "<h2>Notes</h2>"},
                {"type": "code", "value": {"language": "python", "source": "print('hi')"}},
            ],
        }
        return api_client.post(create_url, payload, format="json").json()

    def test_reads_back_normalized_overview(self, api_client, blog, admin_user):
        created = self._create(api_client, blog, admin_user)
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})
        response = api_client.get(url, format="json")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == created["id"]
        assert data["status"] == "draft"
        assert data["tags"] == ["weeknotes"]
        assert data["overview"] == [
            {"type": "paragraph", "value": "<h2>Notes</h2>"},
            {"type": "code", "value": {"language": "python", "source": "print('hi')"}},
        ]

    def test_rejects_caller_without_edit_permission(self, api_client, blog, admin_user):
        created = self._create(api_client, blog, admin_user)
        stranger = UserFactory()
        grant_wagtail_admin_access(stranger)
        api_client.force_authenticate(user=stranger)
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})
        response = api_client.get(url, format="json")
        assert response.status_code == 403

    def test_detail_requires_wagtail_admin_access_even_with_change_permission(self, api_client, blog, admin_user):
        created = self._create(api_client, blog, admin_user)
        user = page_permission_user(codenames=("change_page",))
        api_client.force_authenticate(user=user)
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})

        response = api_client.get(url, format="json")

        assert response.status_code == 403

    def test_detail_without_overview_block_returns_empty_overview(self, api_client, blog, admin_user):
        # A page whose body has only a detail section (no overview) reads back an empty overview.
        from tests.factories import PostFactory

        post = PostFactory(
            owner=blog.owner,
            parent=blog,
            title="Detail only",
            slug="detail-only",
            body=json.dumps([{"type": "detail", "value": [{"type": "paragraph", "value": "<h2>d</h2>"}]}]),
        )
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": post.id})
        response = api_client.get(url, format="json")
        assert response.status_code == 200
        assert response.json()["overview"] == []

    def test_missing_post_returns_404(self, api_client, blog, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": 999999})
        response = api_client.get(url, format="json")
        assert response.status_code == 404
        assert response.json() == {"code": "not_found", "detail": "Post not found."}

    def test_cover_image_round_trip(self, api_client, blog, superuser, image):
        # The author must be able to choose the cover image; a superuser can.
        api_client.force_authenticate(user=superuser)
        create_url = reverse("cast:api:editor_post_create")
        payload = {
            "parent": {"id": blog.id},
            "title": "Post with cover",
            "slug": "cover-draft",
            "tags": ["weeknotes"],
            "overview": [
                {"type": "paragraph", "value": "<h2>Notes</h2>"},
            ],
            "cover_image": {"id": image.id, "alt_text": "Desk photo"},
        }
        response = api_client.post(create_url, payload, format="json")
        assert response.status_code == 201
        created = response.json()

        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})
        response = api_client.get(url, format="json")
        assert response.status_code == 200
        data = response.json()
        assert data["cover_image"] == {"id": image.id, "alt_text": "Desk photo"}


class TestEditorPostUpdate:
    pytestmark = pytest.mark.django_db

    def _create(self, api_client, blog, user, **overrides):
        api_client.force_authenticate(user=user)
        create_url = reverse("cast:api:editor_post_create")
        payload = {
            "parent": {"id": blog.id},
            "title": "Editable draft",
            "slug": "editable-draft",
            "tags": ["weeknotes"],
            "overview": [
                {"type": "paragraph", "value": "<h2>Notes</h2>"},
                {"type": "paragraph", "value": "<p>Original text.</p>"},
            ],
        }
        payload.update(overrides)
        response = api_client.post(create_url, payload, format="json")
        assert response.status_code == 201, response.content
        return response.json()

    def test_requires_authentication(self, api_client, blog, admin_user):
        created = self._create(api_client, blog, admin_user)
        api_client.force_authenticate(user=None)
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})
        response = api_client.patch(url, {"base_revision_id": created["latest_revision_id"], "title": "Nope"})
        assert response.status_code in (401, 403)

    def test_missing_base_revision_is_validation_error(self, api_client, blog, admin_user):
        created = self._create(api_client, blog, admin_user)
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})
        response = api_client.patch(url, {"title": "No base"}, format="json")
        assert response.status_code == 400
        body = response.json()
        assert body["code"] == "validation_error"
        assert "base_revision_id" in body["errors"]

    def test_patch_accepts_if_match_revision_token(self, api_client, blog, admin_user):
        created = self._create(api_client, blog, admin_user)
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})

        response = api_client.patch(
            url,
            {"title": "Header revision"},
            format="json",
            HTTP_IF_MATCH=f'"{created["latest_revision_id"]}"',
        )

        assert response.status_code == 200, response.content
        data = response.json()
        assert data["title"] == "Header revision"
        assert data["latest_revision_id"] != created["latest_revision_id"]

    def test_patch_accepts_if_match_revision_token_with_whitespace(self, api_client, blog, admin_user):
        created = self._create(api_client, blog, admin_user)
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})

        response = api_client.patch(
            url,
            {"title": "Header revision"},
            format="json",
            HTTP_IF_MATCH=f'  "{created["latest_revision_id"]}"  ',
        )

        assert response.status_code == 200, response.content
        assert response.json()["title"] == "Header revision"

    def test_patch_accepts_matching_if_match_and_body_revision(self, api_client, blog, admin_user):
        created = self._create(api_client, blog, admin_user)
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})

        response = api_client.patch(
            url,
            {"base_revision_id": created["latest_revision_id"], "title": "Matching revision"},
            format="json",
            HTTP_IF_MATCH=f'"{created["latest_revision_id"]}"',
        )

        assert response.status_code == 200, response.content
        assert response.json()["title"] == "Matching revision"

    def test_patch_rejects_mismatched_if_match_and_body_revision(self, api_client, blog, admin_user):
        created = self._create(api_client, blog, admin_user)
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})

        response = api_client.patch(
            url,
            {"base_revision_id": created["latest_revision_id"], "title": "Mismatch"},
            format="json",
            HTTP_IF_MATCH=f'"{created["latest_revision_id"] + 1}"',
        )

        assert response.status_code == 400
        body = response.json()
        assert body["code"] == "validation_error"
        assert body["errors"]["If-Match"][0]["code"] == "mismatch"

    @pytest.mark.parametrize("if_match", ["123", 'W/"123"', "*", "", '"123", "456"', '"abc"', '""', '"²"'])
    def test_patch_rejects_malformed_if_match_revision_token(self, api_client, blog, admin_user, if_match):
        created = self._create(api_client, blog, admin_user)
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})

        response = api_client.patch(
            url,
            {"title": "Malformed header"},
            format="json",
            HTTP_IF_MATCH=if_match,
        )

        assert response.status_code == 400
        body = response.json()
        assert body["code"] == "validation_error"
        assert body["errors"]["If-Match"][0]["code"] == "invalid"

    def test_patch_without_any_update_field_is_validation_error(self, api_client, blog, admin_user):
        created = self._create(api_client, blog, admin_user)
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})
        response = api_client.patch(url, {"base_revision_id": created["latest_revision_id"]}, format="json")
        assert response.status_code == 400
        assert response.json()["errors"]["non_field_errors"][0]["code"] == "required"

    def test_patch_with_only_if_match_revision_is_validation_error(self, api_client, blog, admin_user):
        created = self._create(api_client, blog, admin_user)
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})

        response = api_client.patch(url, {}, format="json", HTTP_IF_MATCH=f'"{created["latest_revision_id"]}"')

        assert response.status_code == 400
        assert response.json()["errors"]["non_field_errors"][0]["code"] == "required"

    def test_patch_publish_true_is_rejected(self, api_client, blog, admin_user):
        created = self._create(api_client, blog, admin_user)
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})
        response = api_client.patch(
            url,
            {"base_revision_id": created["latest_revision_id"], "publish": True},
            format="json",
        )
        assert response.status_code == 400
        assert response.json()["errors"]["publish"][0]["code"] == "unsupported"

    def test_stale_base_revision_returns_conflict_without_overwrite(self, api_client, blog, admin_user):
        created = self._create(api_client, blog, admin_user)
        post = Post.objects.get(id=created["id"]).specific
        human_draft = post.get_latest_revision_as_object()
        human_draft.title = "Human draft"
        human_revision = human_draft.save_revision(user=admin_user)

        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})
        response = api_client.patch(
            url,
            {"base_revision_id": created["latest_revision_id"], "title": "Agent draft"},
            format="json",
        )

        assert response.status_code == 409
        body = response.json()
        assert body["code"] == "revision_conflict"
        assert body["detail"] == "The page has a newer revision than the submitted base revision."
        assert body["current_revision_id"] == human_revision.id
        assert body["submitted_base_revision_id"] == created["latest_revision_id"]
        assert body["edit_url"].endswith(f"/pages/{created['id']}/edit/")
        detail = api_client.get(url, format="json").json()
        assert detail["title"] == "Human draft"
        assert detail["latest_revision_id"] == human_revision.id

    def test_stale_if_match_revision_returns_conflict_without_overwrite(self, api_client, blog, admin_user):
        created = self._create(api_client, blog, admin_user)
        post = Post.objects.get(id=created["id"]).specific
        human_draft = post.get_latest_revision_as_object()
        human_draft.title = "Human draft"
        human_revision = human_draft.save_revision(user=admin_user)

        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})
        response = api_client.patch(
            url,
            {"title": "Agent draft"},
            format="json",
            HTTP_IF_MATCH=f'"{created["latest_revision_id"]}"',
        )

        assert response.status_code == 409
        body = response.json()
        assert body["code"] == "revision_conflict"
        assert body["current_revision_id"] == human_revision.id
        assert body["submitted_base_revision_id"] == created["latest_revision_id"]
        detail = api_client.get(url, format="json").json()
        assert detail["title"] == "Human draft"

    def test_patch_updates_only_sent_fields(self, api_client, blog, admin_user):
        created = self._create(api_client, blog, admin_user)
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})

        response = api_client.patch(
            url,
            {"base_revision_id": created["latest_revision_id"], "title": "Retitled draft"},
            format="json",
        )

        assert response.status_code == 200, response.content
        data = response.json()
        assert data["latest_revision_id"] != created["latest_revision_id"]
        assert data["title"] == "Retitled draft"
        assert data["slug"] == "editable-draft"
        assert data["tags"] == ["weeknotes"]
        assert data["overview"] == [
            {"type": "paragraph", "value": "<h2>Notes</h2>"},
            {"type": "paragraph", "value": "<p>Original text.</p>"},
        ]
        assert data["live"] is False

    def test_patch_saves_new_revision_and_round_trips(self, api_client, blog, superuser, image):
        category = PostCategory.objects.create(name="Updated", slug="updated")
        created = self._create(api_client, blog, superuser, slug="all-fields")
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})
        overview = [
            {"type": "paragraph", "value": "<p>Updated draft text.</p>"},
            {"type": "image", "value": {"id": image.id}},
        ]

        response = api_client.patch(
            url,
            {
                "base_revision_id": created["latest_revision_id"],
                "title": "Updated draft",
                "slug": "updated-draft",
                "visible_date": "2026-06-23T08:15:00+02:00",
                "tags": ["weeknotes", "updated"],
                "categories": [category.id],
                "cover_image": {"id": image.id, "alt_text": "Updated alt"},
                "overview": overview,
            },
            format="json",
        )

        assert response.status_code == 200, response.content
        data = response.json()
        assert data["latest_revision_id"] != created["latest_revision_id"]
        assert data["title"] == "Updated draft"
        assert data["slug"] == "updated-draft"
        assert data["tags"] == ["weeknotes", "updated"]
        assert data["categories"] == [category.id]
        assert data["cover_image"] == {"id": image.id, "alt_text": "Updated alt"}
        assert data["overview"] == overview
        assert data["visible_date"].startswith("2026-06-23T")
        assert data["live"] is False
        assert data["status"] == "draft"

        detail = api_client.get(url, format="json").json()
        assert detail["latest_revision_id"] == data["latest_revision_id"]
        assert detail["title"] == "Updated draft"
        assert detail["tags"] == ["weeknotes", "updated"]
        assert detail["categories"] == [category.id]
        assert detail["cover_image"] == {"id": image.id, "alt_text": "Updated alt"}
        assert detail["overview"] == overview

        revision_post = Post.objects.get(id=created["id"]).get_latest_revision().as_object()
        assert [tag.name for tag in revision_post.tags.all()] == ["weeknotes", "updated"]
        assert [saved_category.pk for saved_category in revision_post.categories.all()] == [category.id]
        assert revision_post.cover_image_id == image.id

        stored_post = Post.objects.get(id=created["id"])
        assert stored_post.title == "Editable draft"
        assert stored_post.slug == "all-fields"
        assert stored_post.cover_image_id is None

    def test_patch_chains_returned_revision_id(self, api_client, blog, admin_user):
        created = self._create(api_client, blog, admin_user, slug="chainable")
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})
        first = api_client.patch(
            url,
            {"base_revision_id": created["latest_revision_id"], "title": "First update"},
            format="json",
        ).json()

        second = api_client.patch(
            url,
            {"base_revision_id": first["latest_revision_id"], "title": "Second update"},
            format="json",
        )

        assert second.status_code == 200, second.content
        data = second.json()
        assert data["title"] == "Second update"
        assert data["latest_revision_id"] != first["latest_revision_id"]

    def test_patch_live_page_reports_unpublished_draft_status(self, api_client, blog, admin_user):
        from tests.factories import PostFactory

        post = PostFactory(
            owner=blog.owner,
            parent=blog,
            title="Live page",
            slug="live-page",
            body=json.dumps([{"type": "overview", "value": [{"type": "paragraph", "value": "<h2>Live</h2>"}]}]),
        )
        revision = post.save_revision(user=admin_user, changed=False)
        post.refresh_from_db()
        assert post.live is True
        assert post.has_unpublished_changes is False

        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": post.id})
        response = api_client.patch(
            url,
            {"base_revision_id": revision.id, "title": "Draft over live"},
            format="json",
        )

        assert response.status_code == 200, response.content
        data = response.json()
        assert data["live"] is True
        assert data["status"] == "draft"
        assert data["title"] == "Draft over live"
        post.refresh_from_db()
        assert post.has_unpublished_changes is True

    def test_patch_from_user_without_edit_permission_is_rejected(self, api_client, blog, admin_user):
        created = self._create(api_client, blog, admin_user)
        stranger = UserFactory()
        grant_wagtail_admin_access(stranger)
        api_client.force_authenticate(user=stranger)
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})
        response = api_client.patch(
            url,
            {"base_revision_id": created["latest_revision_id"], "title": "No permission"},
            format="json",
        )
        assert response.status_code == 403
        assert response.json()["code"] == "permission_denied"

    def test_patch_can_clear_cover_image(self, api_client, blog, superuser, image):
        created = self._create(
            api_client,
            blog,
            superuser,
            slug="clear-cover",
            cover_image={"id": image.id, "alt_text": "Desk photo"},
        )
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})
        response = api_client.patch(
            url,
            {"base_revision_id": created["latest_revision_id"], "cover_image": None},
            format="json",
        )
        assert response.status_code == 200, response.content
        assert response.json()["cover_image"] is None

    def test_patch_rejects_unknown_category(self, api_client, blog, admin_user):
        created = self._create(api_client, blog, admin_user, slug="bad-category")
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})
        response = api_client.patch(
            url,
            {"base_revision_id": created["latest_revision_id"], "categories": [999999]},
            format="json",
        )
        assert response.status_code == 400
        assert "categories" in response.json()["errors"]

    def test_patch_adds_overview_to_detail_only_body(self, api_client, blog, admin_user):
        from tests.factories import PostFactory

        post = PostFactory(
            owner=blog.owner,
            parent=blog,
            title="Detail only patch",
            slug="detail-only-patch",
            body=json.dumps([{"type": "detail", "value": [{"type": "paragraph", "value": "<h2>Detail</h2>"}]}]),
        )
        revision = post.save_revision(user=admin_user)
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": post.id})
        overview = [{"type": "paragraph", "value": "<h2>New overview</h2>"}]

        response = api_client.patch(
            url,
            {"base_revision_id": revision.id, "overview": overview},
            format="json",
        )

        assert response.status_code == 200, response.content
        assert response.json()["overview"] == overview
        draft = Post.objects.get(id=post.id).get_latest_revision_as_object()
        assert [block.block_type for block in draft.body] == ["overview", "detail"]

    def test_patch_adds_detail_after_overview_only_body(self, api_client, blog, admin_user):
        from tests.factories import PostFactory

        post = PostFactory(
            owner=blog.owner,
            parent=blog,
            title="Overview only patch",
            slug="overview-only-patch",
            body=json.dumps([{"type": "overview", "value": [{"type": "paragraph", "value": "<h2>Overview</h2>"}]}]),
        )
        revision = post.save_revision(user=admin_user)
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": post.id})
        detail = [{"type": "paragraph", "value": "<p>New detail.</p>"}]

        response = api_client.patch(
            url,
            {"base_revision_id": revision.id, "detail": detail},
            format="json",
        )

        assert response.status_code == 200, response.content
        assert response.json()["detail"] == detail
        draft = Post.objects.get(id=post.id).get_latest_revision_as_object()
        assert [block.block_type for block in draft.body] == ["overview", "detail"]
