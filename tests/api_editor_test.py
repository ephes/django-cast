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

from tests.factories import BlogFactory, PodcastFactory, PostFactory, UserFactory


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


@pytest.fixture(autouse=True)
def _reset_api_client_auth(request):
    """Reset the module-scoped ``api_client`` auth before each test that uses it.

    ``api_client`` is module-scoped, so a forced authentication in one test would
    otherwise leak into the next and make order-dependent tests pass or fail by luck.
    Only tests that request ``api_client`` are reset — ``force_authenticate(None)``
    calls ``logout()``, which touches the session DB, so pure unit tests must skip it.
    """
    if "api_client" in request.fixturenames:
        request.getfixturevalue("api_client").force_authenticate(user=None)


@pytest.fixture
def superuser(django_user_model):
    """A superuser, which passes every Wagtail page and image ``choose`` permission."""
    return django_user_model.objects.create_superuser(
        username="editor-su", email="editor-su@example.com", password="password"
    )


class TestEditorExceptionHandler:
    def test_validation_error_renders_envelope(self):
        exc = EditorValidationError(
            {"overview.3.value.1.id": [{"code": "not_found", "message": "Image 789 does not exist."}]}
        )
        response = editor_exception_handler(exc, {})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data == {
            "code": "validation_error",
            "errors": {"overview.3.value.1.id": [{"code": "not_found", "message": "Image 789 does not exist."}]},
        }

    def test_permission_denied_renders_envelope(self):
        exc = EditorPermissionDenied("You cannot add posts under this page.", parent_id=123)
        response = editor_exception_handler(exc, {})
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data == {
            "code": "permission_denied",
            "detail": "You cannot add posts under this page.",
            "parent_id": 123,
        }

    def test_permission_denied_without_parent_uses_flat_envelope(self):
        exc = EditorPermissionDenied("You do not have access to the Wagtail admin.", parent_id=None)
        response = editor_exception_handler(exc, {})
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data == {
            "code": "permission_denied",
            "detail": "You do not have access to the Wagtail admin.",
        }

    def test_not_found_renders_envelope(self):
        exc = EditorNotFound("Post not found.")
        response = editor_exception_handler(exc, {})
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.data == {"code": "not_found", "detail": "Post not found."}

    def test_drf_validation_error_mapped_to_envelope(self):
        from rest_framework.exceptions import ErrorDetail, ValidationError

        exc = ValidationError({"title": [ErrorDetail("This field is required.", code="required")]})
        response = editor_exception_handler(exc, {})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["code"] == "validation_error"
        assert response.data["errors"]["title"][0] == {
            "code": "required",
            "message": "This field is required.",
        }

    def test_other_exceptions_delegate_to_default(self):
        from rest_framework.exceptions import NotAuthenticated

        response = editor_exception_handler(NotAuthenticated(), {})
        assert response is not None
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_drf_top_level_list_error_has_clean_keys(self):
        from rest_framework.exceptions import ValidationError

        exc = ValidationError(["Something went wrong."])
        response = editor_exception_handler(exc, {})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert all(not key.startswith(".") for key in response.data["errors"])
        assert response.data["errors"]  # non-empty

    def test_drf_nested_list_error_is_indexed(self):
        from rest_framework.exceptions import ValidationError

        # A list of nested dicts (e.g. per-item errors on a list field) recurses by index.
        exc = ValidationError({"items": [{"sub": ["bad"]}]})
        response = editor_exception_handler(exc, {})
        assert response.data["errors"]["items.0.sub"][0]["message"] == "bad"

    def test_drf_mixed_list_errors_keep_original_nested_indexes(self):
        from rest_framework.exceptions import ValidationError

        exc = ValidationError({"items": ["bad list", {"sub": ["bad item"]}]})
        response = editor_exception_handler(exc, {})
        assert response.data["errors"]["items"][0]["message"] == "bad list"
        assert response.data["errors"]["items.1.sub"][0]["message"] == "bad item"

    def test_drf_scalar_field_value_is_flattened(self):
        from rest_framework.exceptions import ErrorDetail, ValidationError

        # A dict whose value is a bare scalar (not a list) hits the scalar branch.
        exc = ValidationError({"field": ErrorDetail("bad", code="invalid")})
        response = editor_exception_handler(exc, {})
        assert response.data["errors"]["field"][0] == {"code": "invalid", "message": "bad"}


class TestEditorParents:
    pytestmark = pytest.mark.django_db

    def test_requires_authentication(self, api_client, db):
        api_client.force_authenticate(user=None)  # reset state from module-scoped fixture
        url = reverse("cast:api:editor_parents")
        response = api_client.get(url, format="json")
        assert response.status_code in (401, 403)

    def test_requires_wagtail_admin_access_even_with_page_permissions(self, api_client):
        user = page_permission_user(codenames=("add_page",))
        api_client.force_authenticate(user=user)
        url = reverse("cast:api:editor_parents")

        response = api_client.get(url, format="json")

        assert response.status_code == 403
        assert response.json() == {
            "code": "permission_denied",
            "detail": "You do not have access to the Wagtail admin.",
        }

    def test_lists_only_addable_blogs(self, api_client, site):
        owner = UserFactory()
        owner._password = "password"
        blog = BlogFactory(owner=owner, title="Owned blog", slug="owned-blog", parent=site.root_page)
        # A second user with no page permissions must not see the blog.
        other = UserFactory()
        grant_wagtail_admin_access(other)
        api_client.force_authenticate(user=other)
        url = reverse("cast:api:editor_parents")
        empty = api_client.get(url, format="json").json()
        assert all(entry["id"] != blog.id for entry in empty)

    def test_superuser_sees_blog_with_type_and_api_url(self, api_client, blog, django_user_model):
        admin = django_user_model.objects.create_superuser(
            username="root", email="root@example.com", password="password"
        )
        api_client.force_authenticate(user=admin)
        url = reverse("cast:api:editor_parents")
        data = api_client.get(url, format="json").json()
        entry = next(e for e in data if e["id"] == blog.id)
        assert entry["title"] == blog.title
        assert entry["type"] == "cast.Blog"
        assert entry["api_url"].endswith("/editor/posts/")  # create endpoint hint

    def test_lists_podcast_with_specific_type(self, api_client, podcast, django_user_model):
        admin = django_user_model.objects.create_superuser(
            username="root2", email="root2@example.com", password="password"
        )
        api_client.force_authenticate(user=admin)
        url = reverse("cast:api:editor_parents")
        data = api_client.get(url, format="json").json()
        entry = next(e for e in data if e["id"] == podcast.id)
        assert entry["type"] == "cast.Podcast"
        # A podcast's primary content type is an episode, so its create hint points there.
        assert entry["api_url"].endswith("/editor/episodes/")


class TestAuthorBlocksToOverview:
    pytestmark = pytest.mark.django_db

    def test_supported_block_set(self):
        assert SUPPORTED_OVERVIEW_BLOCKS == frozenset(
            {"heading", "paragraph", "code", "image", "gallery", "audio", "video"}
        )

    def test_heading_paragraph_code_pass_through(self, superuser):
        result = author_blocks_to_overview(
            [
                {"type": "heading", "value": "Notes"},
                {"type": "paragraph", "value": "<p>Shipped.</p>"},
                {"type": "code", "value": {"language": "python", "source": "print('hi')"}},
            ],
            user=superuser,
        )
        assert result == [
            {"type": "heading", "value": "Notes"},
            {"type": "paragraph", "value": "<p>Shipped.</p>"},
            {"type": "code", "value": {"language": "python", "source": "print('hi')"}},
        ]

    def test_image_block_resolves_to_pk(self, image, superuser):
        result = author_blocks_to_overview([{"type": "image", "value": {"id": image.id}}], user=superuser)
        assert result == [{"type": "image", "value": image.id}]

    def test_gallery_block_builds_layout_struct(self, image, superuser):
        result = author_blocks_to_overview([{"type": "gallery", "value": [{"id": image.id}]}], user=superuser)
        assert result[0]["type"] == "gallery"
        struct = result[0]["value"]
        assert struct["layout"] == "default"
        assert len(struct["gallery"]) == 1
        item = struct["gallery"][0]
        assert item["type"] == "item"
        assert item["value"] == image.id
        assert isinstance(item["id"], str) and len(item["id"]) > 0

    def test_image_not_choosable_by_caller_reports_not_found(self, image, admin_user):
        # admin_user has page permissions but no image ``choose`` permission, so a
        # real image id must be rejected exactly like a missing one (no enumeration).
        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview([{"type": "image", "value": {"id": image.id}}], user=admin_user)
        assert excinfo.value.error_map["overview.0.value.id"][0]["code"] == "not_found"

    def test_audio_block_resolves_to_pk(self, audio, superuser):
        result = author_blocks_to_overview([{"type": "audio", "value": {"id": audio.id}}], user=superuser)
        assert result == [{"type": "audio", "value": audio.id}]

    def test_audio_not_choosable_by_caller_reports_not_found(self, audio):
        caller = UserFactory()
        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview([{"type": "audio", "value": {"id": audio.id}}], user=caller)
        assert excinfo.value.error_map["overview.0.value.id"][0]["code"] == "not_found"

    def test_audio_value_not_dict_rejected(self, superuser):
        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview([{"type": "audio", "value": 123}], user=superuser)
        assert excinfo.value.error_map["overview.0.value.id"][0]["code"] == "not_found"

    def test_video_block_resolves_to_pk(self, video, superuser):
        result = author_blocks_to_overview([{"type": "video", "value": {"id": video.id}}], user=superuser)
        assert result == [{"type": "video", "value": video.id}]

    def test_video_not_choosable_reports_not_found(self, video):
        caller = UserFactory()
        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview([{"type": "video", "value": {"id": video.id}}], user=caller)
        assert excinfo.value.error_map["overview.0.value.id"][0]["code"] == "not_found"

    def test_unsupported_type_reports_path(self, superuser):
        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview([{"type": "embed", "value": "https://example.com"}], user=superuser)
        assert "overview.0.type" in excinfo.value.error_map
        assert excinfo.value.error_map["overview.0.type"][0]["code"] == "unsupported_block_type"

    def test_code_missing_language_reports_path(self, superuser):
        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview([{"type": "code", "value": {"source": "x"}}], user=superuser)
        assert "overview.0.value.language" in excinfo.value.error_map

    def test_missing_image_reports_nested_path(self, superuser):
        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview(
                [
                    {"type": "heading", "value": "h"},
                    {"type": "gallery", "value": [{"id": 999999}]},
                ],
                user=superuser,
            )
        assert "overview.1.value.0.id" in excinfo.value.error_map
        assert excinfo.value.error_map["overview.1.value.0.id"][0]["code"] == "not_found"

    def test_all_errors_aggregated(self, superuser):
        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview(
                [
                    {"type": "bogus", "value": 1},
                    {"type": "image", "value": {"id": 888888}},
                ],
                user=superuser,
            )
        assert set(excinfo.value.error_map) == {"overview.0.type", "overview.1.value.id"}

    def test_non_list_blocks_rejected(self, superuser):
        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview("not a list", user=superuser)
        assert excinfo.value.error_map["overview"][0]["code"] == "invalid"

    def test_block_missing_type_rejected(self, superuser):
        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview([{"value": "x"}], user=superuser)
        assert excinfo.value.error_map["overview.0.type"][0]["code"] == "required"

    def test_heading_non_string_rejected(self, superuser):
        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview([{"type": "heading", "value": 123}], user=superuser)
        assert excinfo.value.error_map["overview.0.value"][0]["code"] == "invalid"

    def test_paragraph_non_string_rejected(self, superuser):
        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview([{"type": "paragraph", "value": 123}], user=superuser)
        assert excinfo.value.error_map["overview.0.value"][0]["code"] == "invalid"

    def test_paragraph_invalid_richtext_rejected(self, superuser):
        # An empty paragraph fails Wagtail's RichTextBlock required validation.
        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview([{"type": "paragraph", "value": ""}], user=superuser)
        assert excinfo.value.error_map["overview.0.value"][0]["code"] == "invalid"

    def test_code_value_not_dict_rejected(self, superuser):
        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview([{"type": "code", "value": "x"}], user=superuser)
        assert excinfo.value.error_map["overview.0.value"][0]["code"] == "invalid"

    def test_image_value_not_dict_rejected(self, superuser):
        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview([{"type": "image", "value": 123}], user=superuser)
        assert excinfo.value.error_map["overview.0.value.id"][0]["code"] == "not_found"

    def test_empty_gallery_rejected(self, superuser):
        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview([{"type": "gallery", "value": []}], user=superuser)
        assert excinfo.value.error_map["overview.0.value"][0]["code"] == "invalid"


class TestOverviewToAuthorBlocks:
    pytestmark = pytest.mark.django_db

    def test_round_trip(self, image, audio, video, superuser):
        author = [
            {"type": "heading", "value": "Notes"},
            {"type": "paragraph", "value": "<p>Shipped.</p>"},
            {"type": "code", "value": {"language": "python", "source": "print('hi')"}},
            {"type": "image", "value": {"id": image.id}},
            {"type": "gallery", "value": [{"id": image.id}]},
            {"type": "audio", "value": {"id": audio.id}},
            {"type": "video", "value": {"id": video.id}},
        ]
        internal = author_blocks_to_overview(author, user=superuser)
        assert overview_to_author_blocks(internal) == author

    def test_unknown_stored_block_is_placeholder(self):
        internal = [{"type": "embed", "value": "https://example.com"}, {"type": "heading", "value": "h"}]
        assert overview_to_author_blocks(internal) == [
            {"type": "unsupported", "value": {"stored_type": "embed", "position": "overview.0"}},
            {"type": "heading", "value": "h"},
        ]

    def test_malformed_stored_gallery_is_placeholder(self):
        internal = [{"type": "gallery", "value": {"layout": "default", "gallery": [{"type": "item"}]}}]
        assert overview_to_author_blocks(internal) == [
            {"type": "unsupported", "value": {"stored_type": "gallery", "position": "overview.0"}}
        ]

    def test_empty_stored_gallery_is_placeholder(self):
        internal = [{"type": "gallery", "value": {"layout": "default", "gallery": []}}]
        assert overview_to_author_blocks(internal) == [
            {"type": "unsupported", "value": {"stored_type": "gallery", "position": "overview.0"}}
        ]

    def test_malformed_stored_code_is_placeholder(self):
        internal = [{"type": "code", "value": {"language": "python"}}]
        assert overview_to_author_blocks(internal) == [
            {"type": "unsupported", "value": {"stored_type": "code", "position": "overview.0"}}
        ]

    def test_unknown_media_ref_type_is_invalid(self, superuser):
        with pytest.raises(ValueError, match="Unsupported media block type"):
            _media_ref_is_available("unknown", 1, superuser)

    def test_unsupported_placeholder_must_match_existing_block(self, superuser):
        existing = [{"type": "embed", "value": "https://example.com"}]
        preserved = author_blocks_to_overview(
            [{"type": "unsupported", "value": {"stored_type": "embed", "position": "overview.0"}}],
            user=superuser,
            existing_section=existing,
        )
        assert preserved == existing

        moved = author_blocks_to_overview(
            [
                {"type": "heading", "value": "Inserted above"},
                {"type": "unsupported", "value": {"stored_type": "embed", "position": "overview.0"}},
            ],
            user=superuser,
            existing_section=existing,
        )
        assert moved == [{"type": "heading", "value": "Inserted above"}, existing[0]]

        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview(
                [{"type": "unsupported", "value": {"stored_type": "quote", "position": "overview.0"}}],
                user=superuser,
                existing_section=existing,
            )
        assert excinfo.value.error_map["overview.0.value.stored_type"][0]["code"] == "invalid"

        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview(
                [{"type": "unsupported", "value": {"stored_type": "embed", "position": "overview.1"}}],
                user=superuser,
                existing_section=existing,
            )
        assert excinfo.value.error_map["overview.0.value.position"][0]["code"] == "invalid"

        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview(
                [
                    {"type": "unsupported", "value": {"stored_type": "embed", "position": "overview.0"}},
                    {"type": "unsupported", "value": {"stored_type": "embed", "position": "overview.0"}},
                ],
                user=superuser,
                existing_section=existing,
            )
        assert excinfo.value.error_map["overview.1.value.position"][0]["code"] == "duplicate"

        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview([{"type": "unsupported", "value": {}}], user=superuser)
        assert excinfo.value.error_map["overview.0.type"][0]["code"] == "unsupported_block_type"

        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview(
                [{"type": "unsupported", "value": "bad"}], user=superuser, existing_section=existing
            )
        assert excinfo.value.error_map["overview.0.value"][0]["code"] == "invalid"

        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview(
                [{"type": "unsupported", "value": {"position": "overview.0"}}],
                user=superuser,
                existing_section=existing,
            )
        assert excinfo.value.error_map["overview.0.value"][0]["code"] == "invalid"

        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview(
                [{"type": "unsupported", "value": {"stored_type": "embed", "position": "overview.x"}}],
                user=superuser,
                existing_section=existing,
            )
        assert excinfo.value.error_map["overview.0.value.position"][0]["code"] == "invalid"


class TestEditorPostCreate:
    pytestmark = pytest.mark.django_db

    # ``admin_user`` (tests/conftest.py) is a non-superuser Moderator holding
    # GroupPagePermission add_page/change_page/publish_page on the root page, so
    # it has can_add_subpage()/can_edit() on any blog or podcast under the site.
    # Page ownership alone does NOT grant the Wagtail "add" permission, so the
    # blog owner cannot be used as the authorized caller here.

    def _payload(self, page, **overrides):
        payload = {
            "parent": {"id": page.id},
            "title": "Weeknotes 2026-25",
            "slug": "weeknotes-2026-25",
            "tags": ["weeknotes"],
            "overview": [
                {"type": "heading", "value": "Notes"},
                {"type": "paragraph", "value": "<p>Shipped the first draft.</p>"},
                {"type": "code", "value": {"language": "python", "source": "print('hi')"}},
            ],
            "publish": False,
        }
        payload.update(overrides)
        return payload

    def test_requires_authentication(self, api_client, blog):
        url = reverse("cast:api:editor_post_create")
        response = api_client.post(url, self._payload(blog), format="json")
        assert response.status_code in (401, 403)

    def test_requires_wagtail_admin_access_even_with_add_permission(self, api_client, blog):
        user = page_permission_user(codenames=("add_page",))
        api_client.force_authenticate(user=user)
        url = reverse("cast:api:editor_post_create")

        response = api_client.post(url, self._payload(blog), format="json")

        assert response.status_code == 403

    def test_creates_unpublished_draft(self, api_client, blog, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_create")
        response = api_client.post(url, self._payload(blog), format="json")
        assert response.status_code == 201, response.content
        data = response.json()
        post = Post.objects.get(id=data["id"])
        assert post.live is False
        assert data["status"] == "draft"
        assert data["type"] == "cast.Post"
        assert data["parent"]["id"] == blog.id
        assert data["latest_revision_id"] == post.latest_revision_id
        assert data["edit_url"].endswith(f"/pages/{post.id}/edit/")
        assert data["preview_url"].endswith(f"/pages/{post.id}/view_draft/")
        assert data["api_url"].endswith(f"/editor/posts/{post.id}/")
        assert list(post.tags.values_list("name", flat=True)) == ["weeknotes"]
        # the structured input lands in the overview section
        assert post.body[0].block_type == "overview"

    def test_creates_draft_under_podcast(self, api_client, podcast, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_create")
        response = api_client.post(url, self._payload(podcast, slug="weeknotes-pod"), format="json")
        assert response.status_code == 201, response.content
        data = response.json()
        assert data["parent"]["id"] == podcast.id
        assert Post.objects.get(id=data["id"]).get_parent().id == podcast.id

    def test_rejects_caller_without_add_permission(self, api_client, blog):
        stranger = UserFactory()
        grant_wagtail_admin_access(stranger)
        api_client.force_authenticate(user=stranger)
        url = reverse("cast:api:editor_post_create")
        response = api_client.post(url, self._payload(blog), format="json")
        assert response.status_code == 403
        assert response.json()["code"] == "permission_denied"

    def test_unknown_parent_is_validation_error(self, api_client, blog, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_create")
        response = api_client.post(url, self._payload(blog, parent={"id": 999999}), format="json")
        assert response.status_code == 400
        body = response.json()
        assert body["code"] == "validation_error"
        assert "parent" in body["errors"]

    def test_missing_required_field_uses_envelope(self, api_client, blog, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_create")
        payload = self._payload(blog)
        del payload["title"]
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 400
        body = response.json()
        assert body["code"] == "validation_error"
        assert "title" in body["errors"]

    def test_publish_true_is_rejected(self, api_client, blog, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_create")
        response = api_client.post(url, self._payload(blog, publish=True), format="json")
        assert response.status_code == 400
        assert "publish" in response.json()["errors"]

    def test_missing_image_returns_precise_path(self, api_client, blog, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_create")
        payload = self._payload(
            blog,
            slug="weeknotes-img",
            overview=[{"type": "gallery", "value": [{"id": 999999}]}],
        )
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 400
        assert "overview.0.value.0.id" in response.json()["errors"]

    def test_inline_image_not_choosable_by_caller_is_rejected(self, api_client, blog, admin_user, image):
        # admin_user can add the post but lacks image ``choose`` permission, so a real
        # image id is rejected with the same not_found path as a missing image (media IDOR guard).
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_create")
        payload = self._payload(
            blog,
            slug="weeknotes-inline-img",
            overview=[{"type": "image", "value": {"id": image.id}}],
        )
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 400
        assert response.json()["errors"]["overview.0.value.id"][0]["code"] == "not_found"

    def test_choosable_image_creates_draft(self, api_client, blog, superuser, image):
        # A caller who can both add the page and choose the image succeeds.
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_post_create")
        payload = self._payload(
            blog,
            slug="weeknotes-ok-img",
            overview=[{"type": "image", "value": {"id": image.id}}],
        )
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 201, response.content

    def test_duplicate_slug_is_validation_error(self, api_client, blog, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_create")
        first = api_client.post(url, self._payload(blog), format="json")
        assert first.status_code == 201
        second = api_client.post(url, self._payload(blog), format="json")
        assert second.status_code == 400
        assert "slug" in second.json()["errors"]

    def test_visible_date_is_applied(self, api_client, blog, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_create")
        payload = self._payload(blog, slug="weeknotes-date", visible_date="2026-06-19T18:00:00+02:00")
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 201, response.content
        post = Post.objects.get(id=response.json()["id"])
        assert post.visible_date.isoformat().startswith("2026-06-19")

    def test_create_with_categories(self, api_client, blog, admin_user):
        category = PostCategory.objects.create(name="Weeknotes", slug="weeknotes-cat")
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_create")
        payload = self._payload(blog, slug="weeknotes-cat-post", categories=[category.id])
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 201, response.content
        post = Post.objects.get(id=response.json()["id"])
        assert list(post.categories.values_list("pk", flat=True)) == [category.id]

    def test_unknown_category_is_rejected(self, api_client, blog, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_create")
        payload = self._payload(blog, slug="weeknotes-badcat", categories=[999999])
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 400
        assert "categories" in response.json()["errors"]

    def test_create_without_tags_or_categories(self, api_client, blog, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_create")
        payload = self._payload(blog, slug="weeknotes-bare", tags=[], categories=[])
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 201, response.content
        post = Post.objects.get(id=response.json()["id"])
        assert list(post.tags.values_list("name", flat=True)) == []

    def test_create_with_audio_block(self, api_client, blog, superuser, audio):
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_post_create")
        payload = self._payload(
            blog,
            slug="weeknotes-audio",
            overview=[{"type": "heading", "value": "Audio"}, {"type": "audio", "value": {"id": audio.id}}],
        )
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 201, response.content
        post = Post.objects.get(id=response.json()["id"])
        overview = post.body[0].value.raw_data
        assert any(b["type"] == "audio" and b["value"] == audio.id for b in overview)

    def test_cover_image_not_choosable_is_rejected(self, api_client, blog, admin_user, image):
        # admin_user can add the post but cannot choose the image.
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_create")
        payload = self._payload(blog, slug="weeknotes-badcover", cover_image={"id": image.id, "alt_text": "x"})
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 400
        assert response.json()["errors"]["cover_image.id"][0]["code"] == "not_found"


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
                {"type": "heading", "value": "Notes"},
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
            {"type": "heading", "value": "Notes"},
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
            body=json.dumps([{"type": "detail", "value": [{"type": "heading", "value": "d"}]}]),
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
                {"type": "heading", "value": "Notes"},
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
                {"type": "heading", "value": "Notes"},
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

    def test_patch_without_any_update_field_is_validation_error(self, api_client, blog, admin_user):
        created = self._create(api_client, blog, admin_user)
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})
        response = api_client.patch(url, {"base_revision_id": created["latest_revision_id"]}, format="json")
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
            {"type": "heading", "value": "Notes"},
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
            body=json.dumps([{"type": "overview", "value": [{"type": "heading", "value": "Live"}]}]),
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
            body=json.dumps([{"type": "detail", "value": [{"type": "heading", "value": "Detail"}]}]),
        )
        revision = post.save_revision(user=admin_user)
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": post.id})
        overview = [{"type": "heading", "value": "New overview"}]

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
            body=json.dumps([{"type": "overview", "value": [{"type": "heading", "value": "Overview"}]}]),
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


class TestEditorPostPublish:
    pytestmark = pytest.mark.django_db

    def _create_draft(self, api_client, blog, user, **overrides):
        api_client.force_authenticate(user=user)
        create_url = reverse("cast:api:editor_post_create")
        payload = {
            "parent": {"id": blog.id},
            "title": "Publishable draft",
            "slug": "publishable-draft",
            "tags": ["weeknotes"],
            "overview": [
                {"type": "heading", "value": "Notes"},
                {"type": "paragraph", "value": "<p>Ready to publish.</p>"},
            ],
        }
        payload.update(overrides)
        response = api_client.post(create_url, payload, format="json")
        assert response.status_code == 201, response.content
        return response.json()

    def test_requires_authentication(self, api_client, blog, admin_user):
        created = self._create_draft(api_client, blog, admin_user)
        api_client.force_authenticate(user=None)
        url = reverse("cast:api:editor_post_publish", kwargs={"pk": created["id"]})

        response = api_client.post(url, {}, format="json")

        assert response.status_code in (401, 403)

    def test_requires_wagtail_admin_access_even_with_publish_permission(self, api_client, blog, admin_user):
        created = self._create_draft(api_client, blog, admin_user)
        user = page_permission_user(codenames=("change_page", "publish_page"))
        api_client.force_authenticate(user=user)
        url = reverse("cast:api:editor_post_publish", kwargs={"pk": created["id"]})

        response = api_client.post(url, {}, format="json")

        assert response.status_code == 403
        assert response.json() == {
            "code": "permission_denied",
            "detail": "You do not have access to the Wagtail admin.",
        }

    def test_rejects_caller_without_publish_permission(self, api_client, blog, admin_user):
        created = self._create_draft(api_client, blog, admin_user)
        user = page_permission_user(codenames=("change_page",))
        grant_wagtail_admin_access(user)
        api_client.force_authenticate(user=user)
        url = reverse("cast:api:editor_post_publish", kwargs={"pk": created["id"]})

        response = api_client.post(url, {}, format="json")

        assert response.status_code == 403
        assert response.json() == {"code": "permission_denied", "detail": "You cannot publish this post."}

    def test_missing_post_returns_404(self, api_client, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_publish", kwargs={"pk": 999999})

        response = api_client.post(url, {}, format="json")

        assert response.status_code == 404
        assert response.json() == {"code": "not_found", "detail": "Post not found."}

    def test_publishes_draft_post_revision(self, api_client, blog, admin_user):
        created = self._create_draft(api_client, blog, admin_user)
        url = reverse("cast:api:editor_post_publish", kwargs={"pk": created["id"]})

        response = api_client.post(url, {}, format="json")

        assert response.status_code == 200, response.content
        data = response.json()
        post = Post.objects.get(pk=created["id"])
        assert post.live is True
        assert post.has_unpublished_changes is False
        assert post.live_revision_id == created["latest_revision_id"]
        assert data["published_revision_id"] == created["latest_revision_id"]
        assert data["latest_revision_id"] == created["latest_revision_id"]
        assert data["live"] is True
        assert data["status"] == "live"
        assert data["edit_url"].endswith(f"/pages/{post.id}/edit/")
        assert data["preview_url"].endswith(f"/pages/{post.id}/view_draft/")
        assert data["api_url"].endswith(f"/editor/posts/{post.id}/")
        assert data["public_url"] is not None
        assert "publishable-draft" in data["public_url"]

    def test_live_page_with_unpublished_draft_publishes_latest_revision(self, api_client, blog, admin_user):
        post = PostFactory(
            owner=blog.owner,
            parent=blog,
            title="Live title",
            slug="live-with-draft",
            body=json.dumps([{"type": "overview", "value": [{"type": "heading", "value": "Live"}]}]),
        )
        post.save_revision(user=admin_user, changed=False)
        post.refresh_from_db()
        assert post.live is True
        assert post.has_unpublished_changes is False

        draft = post.get_latest_revision_as_object()
        draft.title = "Updated draft title"
        draft.body = json.dumps(
            [{"type": "overview", "value": [{"type": "paragraph", "value": "<p>Published draft.</p>"}]}]
        )
        draft_revision = draft.save_revision(user=admin_user)
        post.refresh_from_db()
        assert post.live is True
        assert post.has_unpublished_changes is True

        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_publish", kwargs={"pk": post.id})
        response = api_client.post(url, {}, format="json")

        assert response.status_code == 200, response.content
        data = response.json()
        post.refresh_from_db()
        assert post.title == "Updated draft title"
        assert post.live_revision_id == draft_revision.id
        assert post.has_unpublished_changes is False
        assert data["title"] == "Updated draft title"
        assert data["overview"] == [{"type": "paragraph", "value": "<p>Published draft.</p>"}]
        assert data["published_revision_id"] == draft_revision.id
        assert data["status"] == "live"

    def test_live_page_without_unpublished_draft_is_rejected(self, api_client, blog, admin_user):
        post = PostFactory(
            owner=blog.owner,
            parent=blog,
            title="Already live",
            slug="already-live",
            body=json.dumps([{"type": "overview", "value": [{"type": "heading", "value": "Live"}]}]),
        )
        post.save_revision(user=admin_user, changed=False)
        post.refresh_from_db()
        assert post.live is True
        assert post.has_unpublished_changes is False

        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_publish", kwargs={"pk": post.id})
        response = api_client.post(url, {}, format="json")

        assert response.status_code == 409
        assert response.json() == {
            "code": "no_unpublished_draft",
            "detail": "This post is already live and has no unpublished draft revision.",
        }

    def test_draft_without_revision_is_rejected(self, api_client, blog, admin_user):
        post = Post(title="No revision", slug="no-revision", owner=blog.owner, live=False, body=json.dumps([]))
        blog.add_child(instance=post)

        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_publish", kwargs={"pk": post.id})
        response = api_client.post(url, {}, format="json")

        assert response.status_code == 409
        assert response.json() == {
            "code": "no_revision",
            "detail": "This post has no draft revision to publish.",
        }


class TestEditorDetailSection:
    pytestmark = pytest.mark.django_db

    def test_create_read_and_patch_detail(self, api_client, blog, superuser, video):
        api_client.force_authenticate(user=superuser)
        create_url = reverse("cast:api:editor_post_create")
        payload = {
            "parent": {"id": blog.id},
            "title": "Detail draft",
            "slug": "detail-draft",
            "overview": [],
            "detail": [
                {"type": "heading", "value": "Detail"},
                {"type": "video", "value": {"id": video.id}},
            ],
        }
        created = api_client.post(create_url, payload, format="json")
        assert created.status_code == 201, created.content
        data = created.json()
        assert data["overview"] == []
        assert data["detail"] == payload["detail"]

        detail_url = reverse("cast:api:editor_post_detail", kwargs={"pk": data["id"]})
        read_back = api_client.get(detail_url, format="json").json()
        assert read_back["detail"] == payload["detail"]

        replacement = [{"type": "paragraph", "value": "<p>Updated detail.</p>"}]
        patched = api_client.patch(
            detail_url,
            {"base_revision_id": data["latest_revision_id"], "detail": replacement},
            format="json",
        )
        assert patched.status_code == 200, patched.content
        assert patched.json()["overview"] == []
        assert patched.json()["detail"] == replacement

    def test_patch_preserves_returned_unsupported_placeholder(self, api_client, blog, admin_user):
        post = Post(
            title="Unsupported detail",
            slug="unsupported-detail",
            owner=blog.owner,
            live=False,
            body=json.dumps(
                [
                    {
                        "type": "detail",
                        "value": [
                            {"type": "embed", "value": "https://example.com"},
                            {"type": "heading", "value": "Old heading"},
                        ],
                    }
                ]
            ),
        )
        blog.add_child(instance=post)
        revision = post.save_revision(user=admin_user)
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": post.id})
        detail = api_client.get(url, format="json").json()["detail"]
        assert detail[0] == {"type": "unsupported", "value": {"stored_type": "embed", "position": "detail.0"}}
        replacement = [detail[0], {"type": "heading", "value": "Replacement"}]

        response = api_client.patch(
            url,
            {"base_revision_id": revision.id, "detail": replacement},
            format="json",
        )

        assert response.status_code == 200, response.content
        assert response.json()["detail"] == replacement
        draft = Post.objects.get(id=post.id).get_latest_revision_as_object()
        stored_detail = draft.body.raw_data[0]["value"]
        assert stored_detail[0]["type"] == "embed"
        assert stored_detail[0]["value"] == "https://example.com"
        assert stored_detail[1] == {"type": "heading", "value": "Replacement"}

    def test_patch_can_move_unsupported_placeholder(self, api_client, blog, admin_user):
        post = Post(
            title="Move unsupported detail",
            slug="move-unsupported-detail",
            owner=blog.owner,
            live=False,
            body=json.dumps([{"type": "detail", "value": [{"type": "embed", "value": "https://example.com"}]}]),
        )
        blog.add_child(instance=post)
        revision = post.save_revision(user=admin_user)
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": post.id})
        placeholder = api_client.get(url, format="json").json()["detail"][0]

        response = api_client.patch(
            url,
            {
                "base_revision_id": revision.id,
                "detail": [{"type": "heading", "value": "Inserted above"}, placeholder],
            },
            format="json",
        )

        assert response.status_code == 200, response.content
        assert response.json()["detail"] == [
            {"type": "heading", "value": "Inserted above"},
            {"type": "unsupported", "value": {"stored_type": "embed", "position": "detail.1"}},
        ]

    def test_patch_can_swap_same_type_unsupported_placeholders(self, api_client, blog, admin_user):
        post = Post(
            title="Swap unsupported detail",
            slug="swap-unsupported-detail",
            owner=blog.owner,
            live=False,
            body=json.dumps(
                [
                    {
                        "type": "detail",
                        "value": [
                            {"type": "embed", "value": "https://example.com/one"},
                            {"type": "embed", "value": "https://example.com/two"},
                        ],
                    }
                ]
            ),
        )
        blog.add_child(instance=post)
        revision = post.save_revision(user=admin_user)
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": post.id})
        detail = api_client.get(url, format="json").json()["detail"]

        response = api_client.patch(
            url, {"base_revision_id": revision.id, "detail": [detail[1], detail[0]]}, format="json"
        )

        assert response.status_code == 200, response.content
        draft = Post.objects.get(id=post.id).get_latest_revision_as_object()
        stored_detail = draft.body.raw_data[0]["value"]
        assert [(block["type"], block["value"]) for block in stored_detail] == [
            ("embed", "https://example.com/two"),
            ("embed", "https://example.com/one"),
        ]
        assert response.json()["detail"] == [
            {"type": "unsupported", "value": {"stored_type": "embed", "position": "detail.0"}},
            {"type": "unsupported", "value": {"stored_type": "embed", "position": "detail.1"}},
        ]

    def test_deleted_media_refs_are_placeholders_and_round_trip(self, api_client, blog, superuser):
        dead_image_id = 999_991
        dead_audio_id = 999_992
        dead_video_id = 999_993
        post = Post(
            title="Dead media refs",
            slug="dead-media-refs",
            owner=blog.owner,
            live=False,
            body=json.dumps(
                [
                    {
                        "type": "detail",
                        "value": [
                            {"type": "image", "value": dead_image_id},
                            {
                                "type": "gallery",
                                "value": {
                                    "layout": "default",
                                    "gallery": [{"id": "gallery-item", "type": "item", "value": dead_image_id}],
                                },
                            },
                            {"type": "audio", "value": dead_audio_id},
                            {"type": "video", "value": dead_video_id},
                        ],
                    }
                ]
            ),
        )
        blog.add_child(instance=post)
        revision = post.save_revision(user=superuser)
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": post.id})

        detail = api_client.get(url, format="json").json()["detail"]

        assert detail == [
            {"type": "unsupported", "value": {"stored_type": "image", "position": "detail.0"}},
            {"type": "unsupported", "value": {"stored_type": "gallery", "position": "detail.1"}},
            {"type": "unsupported", "value": {"stored_type": "audio", "position": "detail.2"}},
            {"type": "unsupported", "value": {"stored_type": "video", "position": "detail.3"}},
        ]
        response = api_client.patch(
            url,
            {
                "base_revision_id": revision.id,
                "detail": [{"type": "heading", "value": "Keep editing"}, *detail],
            },
            format="json",
        )

        assert response.status_code == 200, response.content
        assert response.json()["detail"] == [
            {"type": "heading", "value": "Keep editing"},
            {"type": "unsupported", "value": {"stored_type": "image", "position": "detail.1"}},
            {"type": "unsupported", "value": {"stored_type": "gallery", "position": "detail.2"}},
            {"type": "unsupported", "value": {"stored_type": "audio", "position": "detail.3"}},
            {"type": "unsupported", "value": {"stored_type": "video", "position": "detail.4"}},
        ]

    def test_patch_preserves_malformed_gallery_placeholder(self, api_client, blog, admin_user):
        post = Post(
            title="Malformed gallery",
            slug="malformed-gallery",
            owner=blog.owner,
            live=False,
            body=json.dumps([]),
        )
        blog.add_child(instance=post)
        revision = post.save_revision(user=admin_user)
        malformed_body = [
            {
                "type": "overview",
                "value": [{"type": "gallery", "value": {"layout": "default", "gallery": [{"type": "item"}]}}],
            }
        ]
        revision.content["body"] = malformed_body
        revision.save(update_fields=["content"])
        Post.objects.filter(pk=post.pk).update(body=json.dumps(malformed_body))
        post.refresh_from_db()
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": post.id})
        overview = api_client.get(url, format="json").json()["overview"]
        assert overview == [{"type": "unsupported", "value": {"stored_type": "gallery", "position": "overview.0"}}]

        response = api_client.patch(url, {"base_revision_id": revision.id, "overview": overview}, format="json")

        assert response.status_code == 200, response.content
        assert response.json()["overview"] == overview

    def test_patch_preserves_empty_gallery_placeholder(self, api_client, blog, admin_user):
        post = Post(
            title="Empty gallery",
            slug="empty-gallery",
            owner=blog.owner,
            live=False,
            body=json.dumps(
                [
                    {
                        "type": "overview",
                        "value": [{"type": "gallery", "value": {"layout": "default", "gallery": []}}],
                    }
                ]
            ),
        )
        blog.add_child(instance=post)
        revision = post.save_revision(user=admin_user)
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": post.id})
        overview = api_client.get(url, format="json").json()["overview"]
        assert overview == [{"type": "unsupported", "value": {"stored_type": "gallery", "position": "overview.0"}}]

        response = api_client.patch(url, {"base_revision_id": revision.id, "overview": overview}, format="json")

        assert response.status_code == 200, response.content
        assert response.json()["overview"] == overview

    def test_malformed_section_value_serializes_as_empty_section(self, api_client, blog, admin_user):
        post = Post(
            title="Malformed overview",
            slug="malformed-overview",
            owner=blog.owner,
            live=False,
            body=json.dumps([]),
        )
        blog.add_child(instance=post)
        revision = post.save_revision(user=admin_user)
        malformed_body = [{"type": "overview", "value": {"not": "a-list"}}]
        revision.content["body"] = malformed_body
        revision.save(update_fields=["content"])
        Post.objects.filter(pk=post.pk).update(body=json.dumps(malformed_body))
        api_client.force_authenticate(user=admin_user)

        response = api_client.get(reverse("cast:api:editor_post_detail", kwargs={"pk": post.id}), format="json")

        assert response.status_code == 200
        assert response.json()["overview"] == []


class TestEditorMediaEndpoints:
    pytestmark = pytest.mark.django_db

    def test_media_lists_filter_by_query_and_tag(self, api_client, superuser, image, audio, video):
        image.title = "Desk photo"
        image.tags.add("weeknotes", "desk")
        image.save()
        audio.title = "Episode audio"
        audio.subtitle = "Interview mix"
        audio.tags.add("weeknotes")
        audio.save(duration=False)
        video.title = "Demo clip"
        video.tags.add("weeknotes")
        video.save(poster=False)

        api_client.force_authenticate(user=superuser)

        image_url = reverse("cast:api:editor_media_images")
        image_response = api_client.get(f"{image_url}?q=Desk&tag=weeknotes", format="json")
        assert image_response.status_code == 200
        image_results = image_response.json()["results"]
        assert image_results[0]["id"] == image.id
        assert image_results[0]["file"].startswith("/media/")
        assert image_results[0]["collection"]["id"] == image.collection_id

        audio_url = reverse("cast:api:editor_media_audios")
        audio_response = api_client.get(f"{audio_url}?q=Interview&tag=weeknotes", format="json")
        assert audio_response.status_code == 200
        assert audio_response.json()["results"][0]["id"] == audio.id
        assert audio_response.json()["results"][0]["transcript_diarization_mode"] == "inherit"

        video_url = reverse("cast:api:editor_media_videos")
        video_response = api_client.get(f"{video_url}?q=Demo&tag=weeknotes", format="json")
        assert video_response.status_code == 200
        assert video_response.json()["results"][0]["id"] == video.id

    def test_media_lists_without_query_and_nullable_serialization(self, api_client, superuser, audio, video):
        audio.m4a = None
        audio.save(duration=False)
        video.poster = None
        video.save(poster=False)
        api_client.force_authenticate(user=superuser)

        image_response = api_client.get(reverse("cast:api:editor_media_images"), format="json")
        assert image_response.status_code == 200

        audio_response = api_client.get(reverse("cast:api:editor_media_audios"), format="json")
        assert audio_response.status_code == 200
        audio_item = next(item for item in audio_response.json()["results"] if item["id"] == audio.id)
        assert audio_item["m4a"] is None

        video_response = api_client.get(reverse("cast:api:editor_media_videos"), format="json")
        assert video_response.status_code == 200
        video_item = next(item for item in video_response.json()["results"] if item["id"] == video.id)
        assert video_item["poster"] is None

    def test_media_list_rejects_unsupported_parameter(self, api_client, superuser):
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_images")
        response = api_client.get(f"{url}?tags=weeknotes", format="json")
        assert response.status_code == 400
        assert response.json()["errors"]["tags"][0]["code"] == "unsupported_parameter"

    def test_media_list_out_of_range_page_uses_editor_envelope(self, api_client, superuser):
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_images")
        response = api_client.get(f"{url}?page=999999", format="json")
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"
        assert "Invalid page" in response.json()["detail"]

    def test_media_endpoint_requires_wagtail_admin_access_envelope(self, api_client):
        user = UserFactory(is_staff=True)
        api_client.force_authenticate(user=user)
        response = api_client.get(reverse("cast:api:editor_media_images"), format="json")
        assert response.status_code == 403
        assert response.json() == {
            "code": "permission_denied",
            "detail": "You do not have access to the Wagtail admin.",
        }

    def test_collection_discovery_validation_and_success(self, api_client, superuser):
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_collections")

        missing = api_client.get(url, format="json")
        assert missing.status_code == 400
        assert missing.json()["errors"]["type"][0]["code"] == "required"

        invalid = api_client.get(f"{url}?type=file", format="json")
        assert invalid.status_code == 400
        assert invalid.json()["errors"]["type"][0]["code"] == "invalid_choice"

        valid = api_client.get(f"{url}?type=audio", format="json")
        assert valid.status_code == 200
        assert valid.json()["results"][0]["id"] == Collection.get_first_root_node().id
        assert "breadcrumb" in valid.json()["results"][0]

        image = api_client.get(f"{url}?type=image", format="json")
        assert image.status_code == 200
        video = api_client.get(f"{url}?type=video", format="json")
        assert video.status_code == 200

        root = Collection.get_first_root_node()
        child = root.add_child(instance=Collection(name="Child fallback"))
        assert editor_media._collection_item(child)["ancestors"][0]["id"] == root.id

    def test_collection_discovery_rejects_unsupported_parameter(self, api_client, superuser):
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_collections")
        response = api_client.get(f"{url}?type=audio&q=x", format="json")
        assert response.status_code == 400
        assert response.json()["errors"]["q"][0]["code"] == "unsupported_parameter"

    def test_image_upload_and_no_collection_error(self, api_client, superuser, image_1px):
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_images")
        response = api_client.post(
            url,
            {"title": "Uploaded image", "file": image_1px, "collection": Collection.get_first_root_node().id},
            format="multipart",
        )
        assert response.status_code == 201, response.content
        data = response.json()
        assert data["title"] == "Uploaded image"
        assert data["collection"]["id"] == Collection.get_first_root_node().id

        user = UserFactory(is_staff=True)
        grant_wagtail_admin_access(user)
        api_client.force_authenticate(user=user)
        denied = api_client.post(url, {"title": "No collection", "file": image_1px}, format="multipart")
        assert denied.status_code == 403
        assert denied.json()["code"] == "no_upload_collection"

    def test_image_upload_collection_validation_and_form_errors(self, api_client, superuser):
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_images")

        malformed = api_client.post(url, {"collection": "nope"}, format="multipart")
        assert malformed.status_code == 400
        assert malformed.json()["errors"]["collection"][0]["code"] == "invalid"
        with pytest.raises(EditorValidationError):
            editor_media._parse_collection_id(True)

        missing = api_client.post(url, {"collection": 999999}, format="multipart")
        assert missing.status_code == 400
        assert missing.json()["errors"]["collection"][0]["code"] == "collection_permission_denied"

        form_error = api_client.post(url, {"title": "Missing file"}, format="multipart")
        assert form_error.status_code == 400
        assert form_error.json()["errors"]["file"][0]["code"] == "required"

    def test_image_upload_ambiguous_collection(self, api_client, image_1px):
        image_bytes = image_1px.read()
        user = UserFactory(is_staff=True)
        grant_wagtail_admin_access(user)
        root = Collection.get_first_root_node()
        child = root.add_child(instance=Collection(name="Second media collection"))
        for collection in (root, child):
            for codename in ("add_image", "choose_image"):
                grant_collection_permission(user, collection, app_label="wagtailimages", codename=codename)
        api_client.force_authenticate(user=user)

        response = api_client.post(
            reverse("cast:api:editor_media_images"),
            {
                "title": "Ambiguous",
                "file": SimpleUploadedFile("ambiguous.png", image_bytes, content_type="image/png"),
            },
            format="multipart",
        )

        assert response.status_code == 400
        assert response.json()["errors"]["collection"][0]["code"] == "ambiguous"

        explicit = api_client.post(
            reverse("cast:api:editor_media_images"),
            {
                "title": "Explicit collection",
                "file": SimpleUploadedFile("explicit.png", image_bytes, content_type="image/png"),
                "collection": child.id,
            },
            format="multipart",
        )

        assert explicit.status_code == 201, explicit.content
        assert explicit.json()["collection"]["id"] == child.id

    def test_audio_upload_uses_probe_budget_and_rejects_enabled_diarization(
        self, api_client, superuser, m4a_audio, mp3_audio, mocker
    ):
        run_probe = mocker.patch(
            "cast.models.audio.run_media_probe",
            side_effect=[
                subprocess.CompletedProcess([], 0, stdout=b"1.000000\n"),
                subprocess.CompletedProcess([], 0, stdout=b'{"chapters": []}'),
            ],
        )
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_audios")
        response = api_client.post(url, {"title": "Uploaded audio", "m4a": m4a_audio}, format="multipart")
        assert response.status_code == 201, response.content
        data = response.json()
        assert data["title"] == "Uploaded audio"
        assert data["m4a"].startswith("/media/")
        assert run_probe.call_count == 2

        blocked = api_client.post(
            url,
            {
                "title": "Diarization",
                "transcript_diarization_mode": Audio.TranscriptDiarizationMode.ENABLED,
                "mp3": mp3_audio,
            },
            format="multipart",
        )
        assert blocked.status_code == 400
        assert blocked.json()["errors"]["transcript_diarization_mode"][0]["code"] == "unsupported"

    def test_audio_upload_rejects_multiple_files_and_form_errors(self, api_client, superuser, m4a_audio, mp3_audio):
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_audios")

        missing = api_client.post(url, {"title": "Missing audio"}, format="multipart")
        assert missing.status_code == 400
        assert missing.json()["errors"]["non_field_errors"][0]["code"] == "required"

        too_many = api_client.post(url, {"m4a": m4a_audio, "mp3": mp3_audio}, format="multipart")
        assert too_many.status_code == 400
        assert too_many.json()["errors"]["non_field_errors"][0]["code"] == "too_many_files"

        invalid_upload = SimpleUploadedFile("bad.txt", b"ID3-not-really-enough", content_type="audio/mpeg")
        invalid = api_client.post(url, {"title": "Invalid audio", "mp3": invalid_upload}, format="multipart")
        assert invalid.status_code == 400
        assert invalid.json()["errors"]["mp3"][0]["code"] == "invalid_extension"

    def test_audio_post_save_permission_denied_and_cleanup_failed(self, api_client, superuser, m4a_audio, mocker):
        upload_bytes = m4a_audio.read()
        first_upload = SimpleUploadedFile("first.m4a", upload_bytes, content_type="audio/mp4")
        second_upload = SimpleUploadedFile("second.m4a", upload_bytes, content_type="audio/mp4")
        mocker.patch(
            "cast.models.audio.run_media_probe",
            side_effect=[
                subprocess.CompletedProcess([], 0, stdout=b"1.000000\n"),
                subprocess.CompletedProcess([], 0, stdout=b'{"chapters": []}'),
                subprocess.CompletedProcess([], 0, stdout=b"1.000000\n"),
                subprocess.CompletedProcess([], 0, stdout=b'{"chapters": []}'),
            ],
        )
        mocker.patch.object(
            editor_media.audio_permission_policy, "user_has_permission_for_instance", return_value=False
        )
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_audios")

        denied = api_client.post(url, {"title": "Denied audio", "m4a": first_upload}, format="multipart")
        assert denied.status_code == 403
        assert denied.json()["code"] == "post_save_permission_denied"
        assert not Audio.objects.filter(title="Denied audio").exists()

        mocker.patch("cast.api.editor.media._cleanup_media_object", return_value=False)
        failed = api_client.post(url, {"title": "Cleanup audio", "m4a": second_upload}, format="multipart")
        assert failed.status_code == 500
        assert failed.json()["code"] == "cleanup_failed"

    def test_audio_upload_timeout_cleans_up(self, api_client, superuser, m4a_audio, mocker):
        mocker.patch(
            "cast.models.audio.run_media_probe",
            side_effect=subprocess.TimeoutExpired(cmd="ffprobe", timeout=1),
        )
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_audios")

        response = api_client.post(url, {"title": "Slow audio", "m4a": m4a_audio}, format="multipart")

        assert response.status_code == 422
        assert response.json()["code"] == "probe_timeout"
        assert not Audio.objects.filter(title="Slow audio").exists()

    def test_audio_upload_probe_failure_cleans_up(self, api_client, superuser, m4a_audio, mocker):
        mocker.patch(
            "cast.models.audio.run_media_probe",
            return_value=subprocess.CompletedProcess([], 0, stdout=b"N/A\n"),
        )
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_audios")

        response = api_client.post(url, {"title": "Bad duration audio", "m4a": m4a_audio}, format="multipart")

        assert response.status_code == 422
        assert response.json()["code"] == "probe_failed"
        assert not Audio.objects.filter(title="Bad duration audio").exists()

    def test_audio_upload_probe_oserror_cleans_up(self, api_client, superuser, m4a_audio, mocker):
        mocker.patch("cast.models.audio.run_media_probe", side_effect=OSError("ffprobe missing"))
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_audios")

        response = api_client.post(url, {"title": "Missing ffprobe audio", "m4a": m4a_audio}, format="multipart")

        assert response.status_code == 422
        assert response.json()["code"] == "probe_failed"
        assert not Audio.objects.filter(title="Missing ffprobe audio").exists()

    def test_audio_upload_probe_failure_cleanup_failed(self, api_client, superuser, m4a_audio, mocker):
        mocker.patch(
            "cast.models.audio.run_media_probe",
            side_effect=subprocess.CalledProcessError(returncode=1, cmd="ffprobe"),
        )
        mocker.patch("cast.api.editor.media._cleanup_media_object", return_value=False)
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_audios")

        response = api_client.post(url, {"title": "Bad cleanup audio", "m4a": m4a_audio}, format="multipart")

        assert response.status_code == 500
        assert response.json()["code"] == "cleanup_failed"

    def test_audio_upload_chapter_timeout_keeps_saved_audio(self, api_client, superuser, m4a_audio, mocker):
        run_probe = mocker.patch(
            "cast.models.audio.run_media_probe",
            side_effect=[
                subprocess.CompletedProcess([], 0, stdout=b"1.000000\n"),
                subprocess.TimeoutExpired(cmd="ffprobe", timeout=1),
            ],
        )
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_audios")

        response = api_client.post(
            url, {"title": "Audio without extracted chapters", "m4a": m4a_audio}, format="multipart"
        )

        assert response.status_code == 201, response.content
        audio = Audio.objects.get(id=response.json()["id"])
        assert audio.title == "Audio without extracted chapters"
        assert audio.chaptermarks.count() == 0
        assert run_probe.call_count == 2

    def test_audio_upload_malformed_chapter_marks_keep_saved_audio(self, api_client, superuser, m4a_audio, mocker):
        mocker.patch(
            "cast.models.audio.run_media_probe",
            side_effect=[
                subprocess.CompletedProcess([], 0, stdout=b"1.000000\n"),
                subprocess.CompletedProcess([], 0, stdout=b'{"chapters": [{"start_time": "1.000000", "tags": {}}]}'),
            ],
        )
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_audios")

        response = api_client.post(
            url, {"title": "Audio with malformed chapters", "m4a": m4a_audio}, format="multipart"
        )

        assert response.status_code == 201, response.content
        audio = Audio.objects.get(id=response.json()["id"])
        assert audio.title == "Audio with malformed chapters"
        assert audio.chaptermarks.count() == 0

    def test_editor_media_probe_budget_setting_is_used(self, api_client, superuser, m4a_audio, mocker, settings):
        settings.CAST_EDITOR_MEDIA_PROBE_SECONDS = 3
        budget = mocker.patch("cast.api.editor.media.media_probe_budget", wraps=media_probe.media_probe_budget)
        mocker.patch(
            "cast.models.audio.run_media_probe",
            side_effect=[
                subprocess.CompletedProcess([], 0, stdout=b"1.000000\n"),
                subprocess.CompletedProcess([], 0, stdout=b'{"chapters": []}'),
            ],
        )
        api_client.force_authenticate(user=superuser)

        response = api_client.post(
            reverse("cast:api:editor_media_audios"), {"title": "Budget audio", "m4a": m4a_audio}, format="multipart"
        )

        assert response.status_code == 201, response.content
        budget.assert_called_once_with(3.0)

    def test_audio_upload_timeout_cleanup_failed(self, api_client, superuser, m4a_audio, mocker):
        mocker.patch(
            "cast.models.audio.run_media_probe",
            side_effect=subprocess.TimeoutExpired(cmd="ffprobe", timeout=1),
        )
        mocker.patch("cast.api.editor.media._cleanup_media_object", return_value=False)
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_audios")

        response = api_client.post(url, {"title": "Slow cleanup audio", "m4a": m4a_audio}, format="multipart")

        assert response.status_code == 500
        assert response.json()["code"] == "cleanup_failed"

    def test_audio_video_upload_lock(self, api_client, superuser):
        api_client.force_authenticate(user=superuser)
        cache.set(f"cast:editor-media-upload:{superuser.pk}", "1", timeout=60)
        url = reverse("cast:api:editor_media_audios")
        response = api_client.post(url, {"title": "Locked"}, format="multipart")
        assert response.status_code == 429
        assert response.json()["code"] == "rate_limited"
        cache.delete(f"cast:editor-media-upload:{superuser.pk}")

    def test_upload_lock_does_not_release_another_owner(self, superuser):
        key = f"cast:editor-media-upload:{superuser.pk}"
        cache.delete(key)

        def callback():
            cache.set(key, "other-owner", timeout=60)
            return Response({"ok": True})

        response = editor_media._with_upload_lock(superuser, callback)

        assert response.status_code == 200
        assert cache.get(key) == "other-owner"
        cache.delete(key)

    def test_video_upload_with_supplied_poster(self, api_client, superuser, minimal_mp4, image_1px):
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_videos")

        response = api_client.post(
            url,
            {"title": "Uploaded video", "original": minimal_mp4, "poster": image_1px},
            format="multipart",
        )

        assert response.status_code == 201, response.content
        data = response.json()
        assert data["title"] == "Uploaded video"
        assert data["original"].startswith("/media/")
        assert data["poster"].startswith("/media/")
        assert Video.objects.filter(id=data["id"]).exists()

    def test_video_upload_with_explicit_collection_when_multiple_exist(self, api_client, minimal_mp4, image_1px):
        video_bytes = minimal_mp4.read()
        poster_bytes = image_1px.read()
        user = UserFactory(is_staff=True)
        grant_wagtail_admin_access(user)
        root = Collection.get_first_root_node()
        child = root.add_child(instance=Collection(name="Second video collection"))
        for collection in (root, child):
            for codename in ("add_video", "choose_video"):
                grant_collection_permission(user, collection, app_label="cast", codename=codename)
        api_client.force_authenticate(user=user)

        response = api_client.post(
            reverse("cast:api:editor_media_videos"),
            {
                "title": "Explicit video collection",
                "original": SimpleUploadedFile("explicit.mp4", video_bytes, content_type="video/mp4"),
                "poster": SimpleUploadedFile("explicit.png", poster_bytes, content_type="image/png"),
                "collection": child.id,
            },
            format="multipart",
        )

        assert response.status_code == 201, response.content
        assert response.json()["collection"]["id"] == child.id

    def test_video_upload_poster_probe_timeout_succeeds_without_poster(
        self, api_client, superuser, minimal_mp4, mocker
    ):
        run_probe = mocker.patch(
            "cast.models.video.run_media_probe",
            side_effect=subprocess.TimeoutExpired(cmd="ffprobe", timeout=1),
        )
        api_client.force_authenticate(user=superuser)

        response = api_client.post(
            reverse("cast:api:editor_media_videos"),
            {"title": "Video without poster", "original": minimal_mp4},
            format="multipart",
        )

        assert response.status_code == 201, response.content
        data = response.json()
        assert data["poster"] is None
        assert Video.objects.filter(id=data["id"]).exists()
        assert run_probe.call_count == 1

    def test_video_upload_form_and_post_save_errors(self, api_client, superuser, minimal_mp4, mocker):
        upload_bytes = minimal_mp4.read()
        first_upload = SimpleUploadedFile("first.mp4", upload_bytes, content_type="video/mp4")
        second_upload = SimpleUploadedFile("second.mp4", upload_bytes, content_type="video/mp4")
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_media_videos")

        missing = api_client.post(url, {"title": "Missing original"}, format="multipart")
        assert missing.status_code == 400
        assert missing.json()["errors"]["original"][0]["code"] == "required"

        mocker.patch.object(
            editor_media.video_permission_policy, "user_has_permission_for_instance", return_value=False
        )
        denied = api_client.post(url, {"title": "Denied video", "original": first_upload}, format="multipart")
        assert denied.status_code == 403
        assert denied.json()["code"] == "post_save_permission_denied"

        mocker.patch("cast.api.editor.media._cleanup_media_object", return_value=False)
        failed = api_client.post(url, {"title": "Cleanup video", "original": second_upload}, format="multipart")
        assert failed.status_code == 500
        assert failed.json()["code"] == "cleanup_failed"

    def test_private_media_helpers(self, audio, superuser, mocker):
        assert editor_media._relative_field_url(False) is None
        assert editor_media._collection_ref(object()) is None

        class BrokenField:
            @property
            def url(self):
                raise ValueError

        assert editor_media._relative_field_url(BrokenField()) is None

        class AbsoluteField:
            url = "https://cdn.example.com/media/audio/test.mp3?token=abc"

        assert editor_media._relative_field_url(AbsoluteField()) == "/media/audio/test.mp3?token=abc"

        policy = mocker.Mock()
        policy.user_has_permission_for_instance.return_value = False
        assert editor_media._edit_url(superuser, audio, policy=policy, route_name="castaudio:edit") is None
        policy.user_has_permission_for_instance.return_value = True
        assert editor_media._edit_url(superuser, audio, policy=policy, route_name="missing:route") is None

        class FormError:
            code = None
            messages = ["bad form"]

        class ErrorData(dict):
            def as_data(self):
                return {"__all__": [FormError()]}

        class Form:
            errors = ErrorData()

        assert editor_media._form_errors(Form()) == {"non_field_errors": [{"code": "invalid", "message": "bad form"}]}

        class FailingField:
            name = "stored.bin"

            def delete(self, *, save):
                raise OSError("delete failed")

        class ObjectWithFailingField:
            pk = None
            broken = FailingField()
            _meta = mocker.Mock(label="cast.Broken")

        assert editor_media._cleanup_media_object(ObjectWithFailingField(), ("broken",)) is False

        class EmptyField:
            name = ""

        class UnsavedObject:
            pk = None
            empty = EmptyField()
            _meta = mocker.Mock(label="cast.Empty")

        assert editor_media._cleanup_media_object(UnsavedObject(), ("empty",)) is True


class TestMediaProbeBudget:
    def test_remaining_timeout_defaults_and_budget(self):
        assert media_probe.remaining_probe_timeout(12) == 12
        assert media_probe.media_probe_budget_active() is False
        with media_probe.media_probe_budget(30):
            assert media_probe.media_probe_budget_active() is True
            assert 0 < media_probe.remaining_probe_timeout(60) <= 30
        assert media_probe.media_probe_budget_active() is False

    def test_expired_budget_raises(self):
        with pytest.raises(subprocess.TimeoutExpired):
            with media_probe.media_probe_budget(-1):
                media_probe.remaining_probe_timeout(60)

    def test_run_media_probe_applies_timeout(self, mocker):
        run = mocker.patch("cast.media_probe.subprocess.run")
        media_probe.run_media_probe(["ffprobe"], check=True, timeout=7)
        assert run.call_args.kwargs["timeout"] == 7


class TestEditorEpisodeCreate:
    pytestmark = pytest.mark.django_db

    # ``admin_user`` can add/edit pages anywhere under the site but cannot ``choose``
    # media, so podcast-audio tests that need a real audio reference use ``superuser``.

    def _payload(self, podcast, **overrides):
        payload = {
            "parent": {"id": podcast.id},
            "title": "Episode 12",
            "slug": "episode-12",
            "tags": ["podcast"],
            "overview": [
                {"type": "heading", "value": "Show notes"},
                {"type": "paragraph", "value": "<p>In this episode.</p>"},
            ],
            "publish": False,
        }
        payload.update(overrides)
        return payload

    def test_requires_authentication(self, api_client, podcast):
        url = reverse("cast:api:editor_episode_create")
        response = api_client.post(url, self._payload(podcast), format="json")
        assert response.status_code in (401, 403)

    def test_creates_unpublished_episode_draft(self, api_client, podcast, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_episode_create")
        response = api_client.post(url, self._payload(podcast), format="json")
        assert response.status_code == 201, response.content
        data = response.json()
        episode = Episode.objects.get(id=data["id"])
        assert episode.live is False
        assert data["status"] == "draft"
        assert data["type"] == "cast.Episode"
        assert data["parent"]["id"] == podcast.id
        assert data["latest_revision_id"] == episode.latest_revision_id
        assert data["api_url"].endswith(f"/editor/episodes/{episode.id}/")
        assert data["edit_url"].endswith(f"/pages/{episode.id}/edit/")
        # episode-specific fields are present with model defaults for a bare draft
        assert data["podcast_audio"] is None
        assert data["episode_number"] is None
        assert data["episode_type"] == ""
        assert data["season"] is None
        assert data["keywords"] == ""
        assert data["explicit"] == 1
        assert data["block"] is False
        assert list(episode.tags.values_list("name", flat=True)) == ["podcast"]

    def test_response_shape_parity_with_posts(self, api_client, podcast, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_episode_create")
        data = api_client.post(url, self._payload(podcast), format="json").json()
        shared_baseline = {
            "id",
            "type",
            "title",
            "slug",
            "parent",
            "visible_date",
            "tags",
            "categories",
            "cover_image",
            "overview",
            "detail",
            "latest_revision_id",
            "live",
            "status",
            "preview_url",
            "edit_url",
            "api_url",
        }
        assert shared_baseline <= set(data)

    def test_rejects_blog_parent_with_structured_error(self, api_client, blog, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_episode_create")
        response = api_client.post(url, self._payload(blog), format="json")
        assert response.status_code == 400
        body = response.json()
        assert body["code"] == "validation_error"
        assert "parent" in body["errors"]
        assert body["errors"]["parent"][0]["code"] == "invalid"

    def test_unknown_parent_is_validation_error(self, api_client, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_episode_create")
        response = api_client.post(url, self._payload(type("P", (), {"id": 999999})), format="json")
        assert response.status_code == 400
        assert "parent" in response.json()["errors"]

    def test_rejects_caller_without_add_permission(self, api_client, podcast):
        stranger = UserFactory()
        grant_wagtail_admin_access(stranger)
        api_client.force_authenticate(user=stranger)
        url = reverse("cast:api:editor_episode_create")
        response = api_client.post(url, self._payload(podcast), format="json")
        assert response.status_code == 403
        assert response.json()["code"] == "permission_denied"

    def test_publish_true_is_rejected(self, api_client, podcast, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_episode_create")
        response = api_client.post(url, self._payload(podcast, publish=True), format="json")
        assert response.status_code == 400
        assert response.json()["errors"]["publish"][0]["code"] == "unsupported"
        assert not Episode.objects.filter(slug="episode-12").exists()

    def test_duplicate_slug_is_validation_error(self, api_client, podcast, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_episode_create")
        first = api_client.post(url, self._payload(podcast), format="json")
        assert first.status_code == 201
        second = api_client.post(url, self._payload(podcast), format="json")
        assert second.status_code == 400
        assert "slug" in second.json()["errors"]

    def test_episode_specific_fields_round_trip(self, api_client, podcast, superuser, audio):
        season = Season.objects.create(podcast=podcast, number=2, name="Second season")
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_episode_create")
        payload = self._payload(
            podcast,
            slug="episode-full",
            podcast_audio={"id": audio.id},
            episode_number=12,
            episode_type="full",
            season={"id": season.id},
            keywords="python, django",
            explicit=2,
            block=True,
        )
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 201, response.content
        data = response.json()
        assert data["podcast_audio"] == {"id": audio.id}
        assert data["episode_number"] == 12
        assert data["episode_type"] == "full"
        assert data["season"] == {"id": season.id}
        assert data["keywords"] == "python, django"
        assert data["explicit"] == 2
        assert data["block"] is True

        # round-trips through the read endpoint
        detail_url = reverse("cast:api:editor_episode_detail", kwargs={"pk": data["id"]})
        read_back = api_client.get(detail_url, format="json").json()
        assert read_back["podcast_audio"] == {"id": audio.id}
        assert read_back["episode_number"] == 12
        assert read_back["episode_type"] == "full"
        assert read_back["season"] == {"id": season.id}
        assert read_back["explicit"] == 2
        assert read_back["block"] is True

        episode = Episode.objects.get(id=data["id"]).get_latest_revision_as_object()
        assert episode.podcast_audio_id == audio.id
        assert episode.season_id == season.id

    def test_create_with_all_shared_fields(self, api_client, podcast, superuser, image):
        category = PostCategory.objects.create(name="Interviews", slug="interviews")
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_episode_create")
        payload = self._payload(
            podcast,
            slug="episode-rich",
            visible_date="2026-06-29T09:00:00+02:00",
            categories=[category.id],
            cover_image={"id": image.id, "alt_text": "Cover"},
            detail=[{"type": "paragraph", "value": "<p>Long form.</p>"}],
        )
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 201, response.content
        data = response.json()
        assert data["categories"] == [category.id]
        assert data["cover_image"] == {"id": image.id, "alt_text": "Cover"}
        assert data["detail"] == [{"type": "paragraph", "value": "<p>Long form.</p>"}]
        assert data["visible_date"].startswith("2026-06-29T")

    def test_create_without_tags_or_categories(self, api_client, podcast, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_episode_create")
        payload = self._payload(podcast, slug="episode-bare", tags=[], categories=[])
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 201, response.content
        episode = Episode.objects.get(id=response.json()["id"])
        assert list(episode.tags.values_list("name", flat=True)) == []

    def test_missing_podcast_audio_is_neutral_not_found(self, api_client, podcast, superuser):
        api_client.force_authenticate(user=superuser)
        url = reverse("cast:api:editor_episode_create")
        payload = self._payload(podcast, slug="episode-bad-audio", podcast_audio={"id": 999999})
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 400
        assert response.json()["errors"]["podcast_audio.id"][0]["code"] == "not_found"

    def test_podcast_audio_not_choosable_by_caller_is_rejected(self, api_client, podcast, audio):
        # This caller can add the episode (add_page on root) but cannot choose the audio,
        # so a real audio id is rejected with the same neutral not_found as a missing one.
        caller = page_permission_user(codenames=("add_page",))
        grant_wagtail_admin_access(caller)
        api_client.force_authenticate(user=caller)
        url = reverse("cast:api:editor_episode_create")
        payload = self._payload(podcast, slug="episode-locked-audio", podcast_audio={"id": audio.id})
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 400
        assert response.json()["errors"]["podcast_audio.id"][0]["code"] == "not_found"

    def test_foreign_podcast_season_is_rejected(self, api_client, podcast, site, admin_user):
        other_podcast = PodcastFactory(
            owner=podcast.owner, title="Other podcast", slug="other-podcast", parent=site.root_page
        )
        foreign_season = Season.objects.create(podcast=other_podcast, number=1)
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_episode_create")
        payload = self._payload(podcast, slug="episode-foreign-season", season={"id": foreign_season.id})
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 400
        assert response.json()["errors"]["season"][0]["code"] == "invalid"

    def test_missing_season_is_neutral_validation_error(self, api_client, podcast, admin_user):
        # A missing season and a foreign-podcast season collapse to the same neutral
        # error so a caller cannot enumerate Season ids of podcasts they cannot access.
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_episode_create")
        payload = self._payload(podcast, slug="episode-missing-season", season={"id": 999999})
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 400
        assert response.json()["errors"]["season"][0]["code"] == "invalid"

    def test_invalid_episode_type_is_rejected(self, api_client, podcast, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_episode_create")
        payload = self._payload(podcast, slug="episode-bad-type", episode_type="weekly")
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 400
        assert "episode_type" in response.json()["errors"]

    def test_non_positive_episode_number_is_rejected(self, api_client, podcast, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_episode_create")
        payload = self._payload(podcast, slug="episode-bad-number", episode_number=0)
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 400
        assert "episode_number" in response.json()["errors"]


class TestEditorEpisodeDetail:
    pytestmark = pytest.mark.django_db

    def _create(self, api_client, podcast, user, **overrides):
        api_client.force_authenticate(user=user)
        create_url = reverse("cast:api:editor_episode_create")
        payload = {
            "parent": {"id": podcast.id},
            "title": "Readable episode",
            "slug": "readable-episode",
            "tags": ["podcast"],
            "overview": [{"type": "heading", "value": "Notes"}],
        }
        payload.update(overrides)
        response = api_client.post(create_url, payload, format="json")
        assert response.status_code == 201, response.content
        return response.json()

    def test_reads_back_episode(self, api_client, podcast, admin_user):
        created = self._create(api_client, podcast, admin_user)
        url = reverse("cast:api:editor_episode_detail", kwargs={"pk": created["id"]})
        response = api_client.get(url, format="json")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == created["id"]
        assert data["type"] == "cast.Episode"
        assert data["status"] == "draft"
        assert data["overview"] == [{"type": "heading", "value": "Notes"}]

    def test_plain_post_is_not_an_episode(self, api_client, blog, admin_user):
        post = PostFactory(owner=blog.owner, parent=blog, title="Just a post", slug="just-a-post")
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_episode_detail", kwargs={"pk": post.id})
        response = api_client.get(url, format="json")
        assert response.status_code == 404
        assert response.json() == {"code": "not_found", "detail": "Episode not found."}

    def test_missing_episode_returns_404(self, api_client, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_episode_detail", kwargs={"pk": 999999})
        response = api_client.get(url, format="json")
        assert response.status_code == 404
        assert response.json() == {"code": "not_found", "detail": "Episode not found."}

    def test_rejects_caller_without_edit_permission(self, api_client, podcast, admin_user):
        created = self._create(api_client, podcast, admin_user)
        stranger = UserFactory()
        grant_wagtail_admin_access(stranger)
        api_client.force_authenticate(user=stranger)
        url = reverse("cast:api:editor_episode_detail", kwargs={"pk": created["id"]})
        response = api_client.get(url, format="json")
        assert response.status_code == 403


class TestEditorEpisodeUpdate:
    pytestmark = pytest.mark.django_db

    def _create(self, api_client, podcast, user, **overrides):
        api_client.force_authenticate(user=user)
        create_url = reverse("cast:api:editor_episode_create")
        payload = {
            "parent": {"id": podcast.id},
            "title": "Editable episode",
            "slug": "editable-episode",
            "tags": ["podcast"],
            "overview": [{"type": "heading", "value": "Notes"}],
        }
        payload.update(overrides)
        response = api_client.post(create_url, payload, format="json")
        assert response.status_code == 201, response.content
        return response.json()

    def test_missing_base_revision_is_validation_error(self, api_client, podcast, admin_user):
        created = self._create(api_client, podcast, admin_user)
        url = reverse("cast:api:editor_episode_detail", kwargs={"pk": created["id"]})
        response = api_client.patch(url, {"title": "No base"}, format="json")
        assert response.status_code == 400
        assert "base_revision_id" in response.json()["errors"]

    def test_empty_update_is_validation_error(self, api_client, podcast, admin_user):
        created = self._create(api_client, podcast, admin_user)
        url = reverse("cast:api:editor_episode_detail", kwargs={"pk": created["id"]})
        response = api_client.patch(url, {"base_revision_id": created["latest_revision_id"]}, format="json")
        assert response.status_code == 400
        assert response.json()["errors"]["non_field_errors"][0]["code"] == "required"

    def test_patch_publish_true_is_rejected(self, api_client, podcast, admin_user):
        created = self._create(api_client, podcast, admin_user)
        url = reverse("cast:api:editor_episode_detail", kwargs={"pk": created["id"]})
        response = api_client.patch(
            url, {"base_revision_id": created["latest_revision_id"], "publish": True}, format="json"
        )
        assert response.status_code == 400
        assert response.json()["errors"]["publish"][0]["code"] == "unsupported"

    def test_stale_base_revision_returns_conflict(self, api_client, podcast, admin_user):
        created = self._create(api_client, podcast, admin_user)
        episode = Episode.objects.get(id=created["id"])
        human_draft = episode.get_latest_revision_as_object()
        human_draft.title = "Human draft"
        human_revision = human_draft.save_revision(user=admin_user)

        url = reverse("cast:api:editor_episode_detail", kwargs={"pk": created["id"]})
        response = api_client.patch(
            url, {"base_revision_id": created["latest_revision_id"], "title": "Agent draft"}, format="json"
        )
        assert response.status_code == 409
        body = response.json()
        assert body["code"] == "revision_conflict"
        assert body["current_revision_id"] == human_revision.id
        detail = api_client.get(url, format="json").json()
        assert detail["title"] == "Human draft"

    def test_patch_updates_episode_fields(self, api_client, podcast, superuser, audio):
        season = Season.objects.create(podcast=podcast, number=3)
        created = self._create(api_client, podcast, superuser, slug="patch-episode")
        url = reverse("cast:api:editor_episode_detail", kwargs={"pk": created["id"]})
        response = api_client.patch(
            url,
            {
                "base_revision_id": created["latest_revision_id"],
                "podcast_audio": {"id": audio.id},
                "episode_number": 7,
                "episode_type": "bonus",
                "season": {"id": season.id},
                "keywords": "kw",
                "explicit": 3,
                "block": True,
            },
            format="json",
        )
        assert response.status_code == 200, response.content
        data = response.json()
        assert data["podcast_audio"] == {"id": audio.id}
        assert data["episode_number"] == 7
        assert data["episode_type"] == "bonus"
        assert data["season"] == {"id": season.id}
        assert data["keywords"] == "kw"
        assert data["explicit"] == 3
        assert data["block"] is True
        assert data["live"] is False

    def test_patch_updates_all_shared_fields(self, api_client, podcast, superuser, image):
        category = PostCategory.objects.create(name="Updated", slug="updated-ep")
        created = self._create(api_client, podcast, superuser, slug="patch-shared")
        url = reverse("cast:api:editor_episode_detail", kwargs={"pk": created["id"]})
        overview = [{"type": "paragraph", "value": "<p>Updated overview.</p>"}]
        detail = [{"type": "paragraph", "value": "<p>Updated detail.</p>"}]
        response = api_client.patch(
            url,
            {
                "base_revision_id": created["latest_revision_id"],
                "title": "Updated episode",
                "slug": "updated-episode",
                "visible_date": "2026-06-29T08:15:00+02:00",
                "tags": ["podcast", "updated"],
                "categories": [category.id],
                "cover_image": {"id": image.id, "alt_text": "Updated alt"},
                "overview": overview,
                "detail": detail,
            },
            format="json",
        )
        assert response.status_code == 200, response.content
        data = response.json()
        assert data["title"] == "Updated episode"
        assert data["slug"] == "updated-episode"
        assert data["tags"] == ["podcast", "updated"]
        assert data["categories"] == [category.id]
        assert data["cover_image"] == {"id": image.id, "alt_text": "Updated alt"}
        assert data["overview"] == overview
        assert data["detail"] == detail
        assert data["visible_date"].startswith("2026-06-29T")

    def test_patch_preserves_omitted_episode_fields(self, api_client, podcast, superuser, audio):
        created = self._create(
            api_client, podcast, superuser, slug="preserve-episode", podcast_audio={"id": audio.id}, episode_number=4
        )
        url = reverse("cast:api:editor_episode_detail", kwargs={"pk": created["id"]})
        response = api_client.patch(
            url, {"base_revision_id": created["latest_revision_id"], "title": "Renamed"}, format="json"
        )
        assert response.status_code == 200, response.content
        data = response.json()
        assert data["title"] == "Renamed"
        # untouched episode fields survive the partial update
        assert data["podcast_audio"] == {"id": audio.id}
        assert data["episode_number"] == 4

    def test_patch_can_clear_podcast_audio_and_season(self, api_client, podcast, superuser, audio):
        season = Season.objects.create(podcast=podcast, number=5)
        created = self._create(
            api_client,
            podcast,
            superuser,
            slug="clear-episode",
            podcast_audio={"id": audio.id},
            season={"id": season.id},
        )
        url = reverse("cast:api:editor_episode_detail", kwargs={"pk": created["id"]})
        response = api_client.patch(
            url,
            {"base_revision_id": created["latest_revision_id"], "podcast_audio": None, "season": None},
            format="json",
        )
        assert response.status_code == 200, response.content
        data = response.json()
        assert data["podcast_audio"] is None
        assert data["season"] is None

    def test_patch_rejects_foreign_season(self, api_client, podcast, site, admin_user):
        other_podcast = PodcastFactory(
            owner=podcast.owner, title="Other podcast", slug="other-podcast-patch", parent=site.root_page
        )
        foreign_season = Season.objects.create(podcast=other_podcast, number=1)
        created = self._create(api_client, podcast, admin_user, slug="patch-foreign-season")
        url = reverse("cast:api:editor_episode_detail", kwargs={"pk": created["id"]})
        response = api_client.patch(
            url,
            {"base_revision_id": created["latest_revision_id"], "season": {"id": foreign_season.id}},
            format="json",
        )
        assert response.status_code == 400
        assert response.json()["errors"]["season"][0]["code"] == "invalid"

class TestEditorEpisodePublish:
    pytestmark = pytest.mark.django_db

    # ``admin_user`` can add/edit/publish pages under the site but cannot ``choose``
    # media, so any episode that needs a real ``podcast_audio`` is created by ``superuser``.

    def _create_draft(self, api_client, podcast, user, **overrides):
        api_client.force_authenticate(user=user)
        create_url = reverse("cast:api:editor_episode_create")
        payload = {
            "parent": {"id": podcast.id},
            "title": "Publishable episode",
            "slug": "publishable-episode",
            "tags": ["podcast"],
            "overview": [{"type": "heading", "value": "Notes"}],
        }
        payload.update(overrides)
        response = api_client.post(create_url, payload, format="json")
        assert response.status_code == 201, response.content
        return response.json()

    def test_requires_authentication(self, api_client, podcast, admin_user):
        created = self._create_draft(api_client, podcast, admin_user)
        api_client.force_authenticate(user=None)
        url = reverse("cast:api:editor_episode_publish", kwargs={"pk": created["id"]})

        response = api_client.post(url, {}, format="json")

        assert response.status_code in (401, 403)

    def test_requires_wagtail_admin_access_even_with_publish_permission(self, api_client, podcast, admin_user):
        created = self._create_draft(api_client, podcast, admin_user)
        user = page_permission_user(codenames=("change_page", "publish_page"))
        api_client.force_authenticate(user=user)
        url = reverse("cast:api:editor_episode_publish", kwargs={"pk": created["id"]})

        response = api_client.post(url, {}, format="json")

        assert response.status_code == 403
        assert response.json() == {
            "code": "permission_denied",
            "detail": "You do not have access to the Wagtail admin.",
        }

    def test_rejects_caller_without_publish_permission(self, api_client, podcast, admin_user):
        created = self._create_draft(api_client, podcast, admin_user)
        user = page_permission_user(codenames=("change_page",))
        grant_wagtail_admin_access(user)
        api_client.force_authenticate(user=user)
        url = reverse("cast:api:editor_episode_publish", kwargs={"pk": created["id"]})

        response = api_client.post(url, {}, format="json")

        assert response.status_code == 403
        assert response.json() == {"code": "permission_denied", "detail": "You cannot publish this episode."}

    def test_missing_episode_returns_404(self, api_client, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_episode_publish", kwargs={"pk": 999999})

        response = api_client.post(url, {}, format="json")

        assert response.status_code == 404
        assert response.json() == {"code": "not_found", "detail": "Episode not found."}

    def test_plain_post_is_not_an_episode(self, api_client, blog, admin_user):
        post = PostFactory(owner=blog.owner, parent=blog, title="Just a post", slug="just-a-post-publish")
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_episode_publish", kwargs={"pk": post.id})

        response = api_client.post(url, {}, format="json")

        assert response.status_code == 404
        assert response.json() == {"code": "not_found", "detail": "Episode not found."}

    def test_publishes_draft_episode_with_audio(self, api_client, podcast, superuser, audio):
        created = self._create_draft(
            api_client, podcast, superuser, slug="publishable-with-audio", podcast_audio={"id": audio.id}
        )
        url = reverse("cast:api:editor_episode_publish", kwargs={"pk": created["id"]})

        response = api_client.post(url, {}, format="json")

        assert response.status_code == 200, response.content
        data = response.json()
        episode = Episode.objects.get(pk=created["id"])
        assert episode.live is True
        assert episode.has_unpublished_changes is False
        assert episode.live_revision_id == created["latest_revision_id"]
        assert data["published_revision_id"] == created["latest_revision_id"]
        assert data["type"] == "cast.Episode"
        assert data["live"] is True
        assert data["status"] == "live"
        # episode-shaped response: episode-specific fields and the episode api_url
        assert data["podcast_audio"] == {"id": audio.id}
        assert data["api_url"].endswith(f"/editor/episodes/{episode.id}/")
        assert data["public_url"] is not None
        assert "publishable-with-audio" in data["public_url"]

    def test_publish_without_podcast_audio_is_rejected(self, api_client, podcast, admin_user):
        created = self._create_draft(api_client, podcast, admin_user, slug="publishable-no-audio")
        url = reverse("cast:api:editor_episode_publish", kwargs={"pk": created["id"]})

        response = api_client.post(url, {}, format="json")

        assert response.status_code == 400
        body = response.json()
        assert body["code"] == "validation_error"
        assert body["errors"]["podcast_audio"][0]["code"] == "required"
        episode = Episode.objects.get(pk=created["id"])
        assert episode.live is False

    def test_live_episode_without_unpublished_draft_is_rejected(self, api_client, podcast, superuser, audio):
        created = self._create_draft(
            api_client, podcast, superuser, slug="already-live-episode", podcast_audio={"id": audio.id}
        )
        url = reverse("cast:api:editor_episode_publish", kwargs={"pk": created["id"]})
        first = api_client.post(url, {}, format="json")
        assert first.status_code == 200, first.content

        response = api_client.post(url, {}, format="json")

        assert response.status_code == 409
        assert response.json()["code"] == "no_unpublished_draft"

    def test_post_publish_endpoint_cannot_bypass_episode_audio_gate(self, api_client, podcast, admin_user):
        # An Episode is a Post, so the shipped posts publish endpoint resolves it via
        # ``.specific``; it must still enforce the podcast_audio gate and not publish.
        created = self._create_draft(api_client, podcast, admin_user, slug="bypass-attempt")
        url = reverse("cast:api:editor_post_publish", kwargs={"pk": created["id"]})

        response = api_client.post(url, {}, format="json")

        assert response.status_code == 400
        assert response.json()["errors"]["podcast_audio"][0]["code"] == "required"
        episode = Episode.objects.get(pk=created["id"])
        assert episode.live is False


class TestEditorScopeReader:
    def test_none_auth_returns_none(self):
        from cast.api.editor.scopes import get_request_scopes

        assert get_request_scopes(None) is None

    def test_space_separated_scope_string_is_split(self):
        from cast.api.editor.scopes import get_request_scopes

        token = type("Tok", (), {"scope": "write publish"})()
        assert get_request_scopes(token) == {"write", "publish"}

    def test_scopes_iterable_is_collected(self):
        from cast.api.editor.scopes import get_request_scopes

        token = type("Tok", (), {"scopes": ["write"]})()
        assert get_request_scopes(token) == {"write"}

    def test_token_without_scope_info_returns_none(self):
        from cast.api.editor.scopes import get_request_scopes

        token = type("Tok", (), {})()
        assert get_request_scopes(token) is None

    def test_empty_scope_string_is_empty_set_not_none(self):
        from cast.api.editor.scopes import get_request_scopes

        token = type("Tok", (), {"scope": ""})()
        assert get_request_scopes(token) == set()

    def test_non_string_scope_value_fails_closed(self):
        # ``scope`` is string-only by convention; a list must NOT be coerced into granted
        # scopes (that would fail open). It fails closed to an empty set.
        from cast.api.editor.scopes import get_request_scopes

        token = type("Tok", (), {"scope": ["write"]})()
        assert get_request_scopes(token) == set()

    def test_empty_scopes_iterable_is_empty_set(self):
        from cast.api.editor.scopes import get_request_scopes

        token = type("Tok", (), {"scopes": []})()
        assert get_request_scopes(token) == set()

    def test_scopes_accepts_any_non_string_iterable(self):
        # The contract is "iterable of scope strings", not "list" — a generator works.
        from cast.api.editor.scopes import get_request_scopes

        token = type("Tok", (), {"scopes": iter(["write", "publish"])})()
        assert get_request_scopes(token) == {"write", "publish"}


class TestHasEditorScope:
    def _request(self, method, auth):
        return type("Req", (), {"method": method, "auth": auth})()

    def _view(self, required_scopes):
        return type("View", (), {"required_scopes": required_scopes})()

    def test_options_is_allowed_without_declaration(self):
        from cast.api.editor.scopes import HasEditorScope

        perm = HasEditorScope()
        assert perm.has_permission(self._request("OPTIONS", None), self._view({})) is True

    def test_none_scope_method_is_allowed(self):
        from cast.api.editor.scopes import HasEditorScope

        perm = HasEditorScope()
        assert perm.has_permission(self._request("GET", None), self._view({"GET": None})) is True

    def test_undeclared_method_fails_closed(self):
        from cast.api.editor.errors import EditorFlatError
        from cast.api.editor.scopes import HasEditorScope

        perm = HasEditorScope()
        with pytest.raises(EditorFlatError) as exc:
            perm.has_permission(self._request("PATCH", None), self._view({"GET": None}))
        assert exc.value.code_text == "insufficient_scope"
        assert exc.value.status_code == 403

    def test_session_request_allows_write(self):
        from cast.api.editor.scopes import HasEditorScope

        perm = HasEditorScope()
        # request.auth is None (session) -> defer to Wagtail
        assert perm.has_permission(self._request("POST", None), self._view({"POST": "write"})) is True

    def test_unscoped_token_allows_write(self):
        from cast.api.editor.scopes import HasEditorScope

        perm = HasEditorScope()
        token = type("Tok", (), {})()  # no scope/scopes attribute
        assert perm.has_permission(self._request("POST", token), self._view({"POST": "write"})) is True

    def test_scoped_token_missing_scope_is_denied(self):
        from cast.api.editor.errors import EditorFlatError
        from cast.api.editor.scopes import HasEditorScope

        perm = HasEditorScope()
        token = type("Tok", (), {"scope": "publish"})()  # has publish, needs write
        with pytest.raises(EditorFlatError) as exc:
            perm.has_permission(self._request("POST", token), self._view({"POST": "write"}))
        assert exc.value.code_text == "insufficient_scope"

    def test_write_scope_allows_write_but_not_publish(self):
        from cast.api.editor.errors import EditorFlatError
        from cast.api.editor.scopes import HasEditorScope

        perm = HasEditorScope()
        token = type("Tok", (), {"scope": "write"})()
        assert perm.has_permission(self._request("POST", token), self._view({"POST": "write"})) is True
        with pytest.raises(EditorFlatError):
            perm.has_permission(self._request("POST", token), self._view({"POST": "publish"}))

    def test_publish_scope_allows_publish(self):
        from cast.api.editor.scopes import HasEditorScope

        perm = HasEditorScope()
        token = type("Tok", (), {"scope": "publish"})()
        assert perm.has_permission(self._request("POST", token), self._view({"POST": "publish"})) is True


class TestEditorViewScopeDeclarations:
    pytestmark = pytest.mark.django_db

    def _editor_views(self):
        from cast.api import urls as api_urls

        views = {}
        for pattern in api_urls.urlpatterns:
            name = getattr(pattern, "name", None) or ""
            if not name.startswith("editor_"):
                continue
            cls = getattr(pattern.callback, "cls", None)
            if cls is not None:
                views[name] = cls
        return views

    def test_found_editor_views(self):
        # Guards the guard: make sure the URLconf scan actually finds the views.
        assert "editor_post_create" in self._editor_views()
        assert "editor_episode_publish" in self._editor_views()

    def test_every_served_method_declares_a_required_scope(self):
        valid = {None, "write", "publish"}
        skipped = {"options", "head", "trace"}
        for name, cls in self._editor_views().items():
            methods = [m for m in cls.http_method_names if m not in skipped and hasattr(cls, m)]
            assert methods, f"{name}: no handler methods found"
            for method in methods:
                key = method.upper()
                assert key in cls.required_scopes, f"{name} ({cls.__name__}) does not declare scope for {key}"
                assert cls.required_scopes[key] in valid, f"{name}: bad scope value for {key}"


class _FakeScopedToken:
    def __init__(self, scope: str):
        self.scope = scope


class TestEditorScopeEnforcement:
    pytestmark = pytest.mark.django_db

    def _create_draft(self, api_client, blog, user):
        api_client.force_authenticate(user=user)
        url = reverse("cast:api:editor_post_create")
        payload = {
            "parent": {"id": blog.id},
            "title": "Scope draft",
            "slug": "scope-draft",
            "tags": [],
            "overview": [{"type": "heading", "value": "Notes"}],
        }
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 201, response.content
        return response.json()

    def test_session_request_can_read(self, api_client, blog, admin_user):
        created = self._create_draft(api_client, blog, admin_user)
        # session auth: request.auth is None -> scope layer defers to Wagtail
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})
        assert api_client.get(url, format="json").status_code == 200

    def test_unscoped_token_can_write(self, api_client, blog, admin_user):
        api_client.force_authenticate(user=admin_user, token=type("Tok", (), {})())
        url = reverse("cast:api:editor_post_create")
        payload = {
            "parent": {"id": blog.id},
            "title": "Unscoped write",
            "slug": "unscoped-write",
            "tags": [],
            "overview": [{"type": "heading", "value": "Notes"}],
        }
        assert api_client.post(url, payload, format="json").status_code == 201

    def test_write_scope_can_create(self, api_client, blog, admin_user):
        api_client.force_authenticate(user=admin_user, token=_FakeScopedToken("write"))
        url = reverse("cast:api:editor_post_create")
        payload = {
            "parent": {"id": blog.id},
            "title": "Write scope",
            "slug": "write-scope",
            "tags": [],
            "overview": [{"type": "heading", "value": "Notes"}],
        }
        assert api_client.post(url, payload, format="json").status_code == 201

    def test_missing_scope_is_403_insufficient_scope(self, api_client, blog, admin_user):
        # Token carries 'publish' but creating requires 'write'.
        api_client.force_authenticate(user=admin_user, token=_FakeScopedToken("publish"))
        url = reverse("cast:api:editor_post_create")
        payload = {
            "parent": {"id": blog.id},
            "title": "No write scope",
            "slug": "no-write-scope",
            "tags": [],
            "overview": [{"type": "heading", "value": "Notes"}],
        }
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 403
        assert response.json()["code"] == "insufficient_scope"
        assert not Post.objects.filter(slug="no-write-scope").exists()

    def test_write_scope_cannot_publish(self, api_client, blog, admin_user):
        created = self._create_draft(api_client, blog, admin_user)
        api_client.force_authenticate(user=admin_user, token=_FakeScopedToken("write"))
        url = reverse("cast:api:editor_post_publish", kwargs={"pk": created["id"]})
        response = api_client.post(url, {}, format="json")
        assert response.status_code == 403
        assert response.json()["code"] == "insufficient_scope"
        assert Post.objects.get(pk=created["id"]).live is False

    def test_publish_scope_can_publish(self, api_client, blog, admin_user):
        created = self._create_draft(api_client, blog, admin_user)
        api_client.force_authenticate(user=admin_user, token=_FakeScopedToken("publish"))
        url = reverse("cast:api:editor_post_publish", kwargs={"pk": created["id"]})
        response = api_client.post(url, {}, format="json")
        assert response.status_code == 200, response.content
        assert Post.objects.get(pk=created["id"]).live is True

    def test_scoped_token_can_read_without_scope(self, api_client, blog, admin_user):
        created = self._create_draft(api_client, blog, admin_user)
        # A token scoped only for publish can still GET (reads need no scope).
        api_client.force_authenticate(user=admin_user, token=_FakeScopedToken("publish"))
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})
        assert api_client.get(url, format="json").status_code == 200

    def test_cast_editor_scopes_override_is_honoured(self, api_client, blog, admin_user, settings):
        # Rename the write scope to match a site's issuer vocabulary.
        settings.CAST_EDITOR_SCOPES = {"write": {"posts:edit"}, "publish": {"publish"}}
        api_client.force_authenticate(user=admin_user, token=_FakeScopedToken("posts:edit"))
        url = reverse("cast:api:editor_post_create")
        payload = {
            "parent": {"id": blog.id},
            "title": "Custom scope",
            "slug": "custom-scope",
            "tags": [],
            "overview": [{"type": "heading", "value": "Notes"}],
        }
        assert api_client.post(url, payload, format="json").status_code == 201
