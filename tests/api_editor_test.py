import json

import pytest
from django.contrib.auth.models import Group, Permission
from django.urls import reverse
from rest_framework import status
from wagtail.models import GroupPagePermission, Page

from cast.api.editor.body import SUPPORTED_OVERVIEW_BLOCKS, author_blocks_to_overview, overview_to_author_blocks
from cast.api.editor.errors import (
    EditorNotFound,
    EditorPermissionDenied,
    EditorValidationError,
    editor_exception_handler,
)
from cast.models import Post
from cast.models.snippets import PostCategory

from tests.factories import BlogFactory, UserFactory


def grant_wagtail_admin_access(user) -> None:
    permission = Permission.objects.get(codename="access_admin", content_type__app_label="wagtailadmin")
    user.user_permissions.add(permission)


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


class TestAuthorBlocksToOverview:
    pytestmark = pytest.mark.django_db

    def test_supported_block_set(self):
        assert SUPPORTED_OVERVIEW_BLOCKS == frozenset({"heading", "paragraph", "code", "image", "gallery", "audio"})

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

    def test_audio_not_choosable_by_caller_reports_not_found(self, audio, admin_user):
        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview([{"type": "audio", "value": {"id": audio.id}}], user=admin_user)
        assert excinfo.value.error_map["overview.0.value.id"][0]["code"] == "not_found"

    def test_audio_value_not_dict_rejected(self, superuser):
        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview([{"type": "audio", "value": 123}], user=superuser)
        assert excinfo.value.error_map["overview.0.value.id"][0]["code"] == "not_found"

    def test_unsupported_type_reports_path(self, superuser):
        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview([{"type": "video", "value": {"id": 1}}], user=superuser)
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

    def test_round_trip(self, image, audio, superuser):
        author = [
            {"type": "heading", "value": "Notes"},
            {"type": "paragraph", "value": "<p>Shipped.</p>"},
            {"type": "code", "value": {"language": "python", "source": "print('hi')"}},
            {"type": "image", "value": {"id": image.id}},
            {"type": "gallery", "value": [{"id": image.id}]},
            {"type": "audio", "value": {"id": audio.id}},
        ]
        internal = author_blocks_to_overview(author, user=superuser)
        assert overview_to_author_blocks(internal) == author

    def test_unknown_stored_block_is_skipped(self):
        internal = [{"type": "embed", "value": "https://example.com"}, {"type": "heading", "value": "h"}]
        assert overview_to_author_blocks(internal) == [{"type": "heading", "value": "h"}]


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
