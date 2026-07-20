# ruff: noqa: F401,F811,I001
import json
import subprocess

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.models import Group, Permission
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.response import Response
from wagtail import blocks
from wagtail.models import Collection, GroupCollectionPermission, GroupPagePermission, Page

from cast import media_probe
from cast.api.editor import media as editor_media
from cast.api.editor.body import (
    SUPPORTED_OVERVIEW_BLOCKS,
    _content_section,
    _custom_author_value,
    _custom_block_map,
    _flatten_django_validation_error,
    _media_ref_is_available,
    _unwrap_list_item_values,
    author_blocks_to_overview,
    author_blocks_to_section,
    overview_to_author_blocks,
    section_to_author_blocks,
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


WEEKNOTE_LINK = {
    "category": "articles",
    "kind": "article",
    "title": "Example article",
    "url": "https://example.com/article",
    "source": "Example",
    "source_url": "",
    "description": "<p>Short summary.</p>",
}


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


class TestEditorCustomBlockHelpers:
    def test_unknown_path_prefix_has_no_custom_blocks(self):
        assert _content_section("not-body") is None
        assert _custom_block_map(None) == {}

    def test_django_validation_error_dict_is_flattened(self):
        exc = DjangoValidationError({"title": [DjangoValidationError("Bad title", code="invalid")]})

        assert _flatten_django_validation_error(exc, "overview.0.value") == {
            "overview.0.value.title": [{"code": "invalid", "message": "Bad title"}]
        }

    def test_wagtail_non_block_errors_are_flattened(self):
        exc = DjangoValidationError("Container failed")
        exc.non_block_errors = [DjangoValidationError("Bad list", code="invalid")]

        assert _flatten_django_validation_error(exc, "overview.0.value") == {
            "overview.0.value": [{"code": "invalid", "message": "Bad list"}]
        }

    def test_non_validation_children_are_ignored_until_leaf_fallback(self):
        exc = DjangoValidationError("Container failed")
        exc.block_errors = {"field": "not a validation error"}

        assert _flatten_django_validation_error(exc, "overview.0.value") == {
            "overview.0.value": [{"code": "invalid", "message": "Container failed"}]
        }

    def test_non_validation_non_block_children_are_ignored_until_leaf_fallback(self):
        exc = DjangoValidationError("Container failed")
        exc.non_block_errors = ["not a validation error"]

        assert _flatten_django_validation_error(exc, "overview.0.value") == {
            "overview.0.value": [{"code": "invalid", "message": "Container failed"}]
        }

    def test_non_validation_error_dict_children_are_ignored_until_leaf_fallback(self):
        exc = DjangoValidationError("Container failed")
        exc.error_dict = {"field": ["not a validation error"]}

        assert _flatten_django_validation_error(exc, "overview.0.value") == {
            "overview.0.value": [{"code": "invalid", "message": "not a validation error"}]
        }

    def test_base_block_author_value_uses_prep_value_fallback(self):
        class PlainBlock(blocks.Block):
            pass

        assert _custom_author_value(PlainBlock(), {"nested": ["value"]}) == {"nested": ["value"]}

    def test_list_item_unwrap_handles_plain_lists_and_nested_dicts(self):
        assert _unwrap_list_item_values(
            {
                "items": [
                    {"type": "item", "id": "a", "value": {"title": "A"}},
                    {"type": "item", "id": "b", "value": {"title": "B"}},
                ],
                "plain": [1, {"x": 2}],
            }
        ) == {"items": [{"title": "A"}, {"title": "B"}], "plain": [1, {"x": 2}]}


class TestEditorParents:
    pytestmark = pytest.mark.django_db

    def test_requires_authentication(self, api_client, db):
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
        assert SUPPORTED_OVERVIEW_BLOCKS == frozenset({"paragraph", "code", "image", "gallery", "audio", "video"})

    def test_paragraph_code_pass_through(self, superuser):
        result = author_blocks_to_overview(
            [
                {"type": "paragraph", "value": "<h2>Notes</h2>"},
                {"type": "paragraph", "value": "<p>Shipped.</p>"},
                {"type": "code", "value": {"language": "python", "source": "print('hi')"}},
            ],
            user=superuser,
        )
        assert result == [
            {"type": "paragraph", "value": "<h2>Notes</h2>"},
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

    def test_image_not_choosable_by_caller_reports_not_found(self, image):
        # A caller with no image ``choose`` permission sees a real image id rejected
        # exactly like a missing one (no enumeration).
        caller = UserFactory(is_staff=True)
        grant_wagtail_admin_access(caller)
        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview([{"type": "image", "value": {"id": image.id}}], user=caller)
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
                    {"type": "paragraph", "value": "<h2>h</h2>"},
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

    def test_heading_block_type_rejected(self, superuser):
        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview([{"type": "heading", "value": "Notes"}], user=superuser)
        assert excinfo.value.error_map["overview.0.type"][0]["code"] == "unsupported_block_type"

    def test_non_string_block_type_rejected(self, superuser):
        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview([{"type": 1, "value": "Notes"}], user=superuser)
        assert excinfo.value.error_map["overview.0.type"][0]["code"] == "unsupported_block_type"

    @override_settings(CAST_POST_BODY_BLOCKS={"overview": ["tests.custom_post_body_blocks.weeknote_links_block"]})
    def test_configured_custom_list_block_round_trips_without_internal_item_wrappers(self, superuser):
        author = [{"type": "weeknote_links", "value": [WEEKNOTE_LINK]}]

        internal = author_blocks_to_overview(author, user=superuser)

        assert internal[0]["type"] == "weeknote_links"
        assert internal[0]["value"][0]["type"] == "item"
        assert internal[0]["value"][0]["value"] == WEEKNOTE_LINK
        assert overview_to_author_blocks(internal) == author

    @override_settings(CAST_POST_BODY_BLOCKS={"overview": ["tests.custom_post_body_blocks.weeknote_links_block"]})
    def test_configured_custom_block_validation_errors_are_field_precise(self, superuser):
        bad_link = {**WEEKNOTE_LINK, "title": "", "url": "not-a-url"}

        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview([{"type": "weeknote_links", "value": [bad_link]}], user=superuser)

        assert excinfo.value.error_map["overview.0.value.0.title"][0]["code"] == "required"
        assert excinfo.value.error_map["overview.0.value.0.url"][0]["code"] == "invalid"

    @override_settings(CAST_POST_BODY_BLOCKS={"overview": ["tests.custom_post_body_blocks.raising_to_python_block"]})
    def test_configured_custom_block_conversion_errors_are_validation_errors(self, superuser):
        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview([{"type": "raising_custom", "value": "boom"}], user=superuser)

        assert excinfo.value.error_map["overview.0.value"] == [
            {"code": "invalid", "message": "custom conversion failed"}
        ]

    @override_settings(CAST_POST_BODY_BLOCKS={"overview": ["tests.custom_post_body_blocks.weeknote_links_block"]})
    def test_configured_custom_block_is_section_scoped(self, superuser):
        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_section(
                [{"type": "weeknote_links", "value": [WEEKNOTE_LINK]}], user=superuser, path_prefix="detail"
            )

        assert excinfo.value.error_map["detail.0.type"][0]["code"] == "unsupported_block_type"

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
            {"type": "paragraph", "value": "<h2>Notes</h2>"},
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
            {"type": "unsupported", "value": {"stored_type": "heading", "position": "overview.1"}},
        ]

    def test_unconfigured_stored_custom_block_is_placeholder(self):
        internal = [{"type": "weeknote_links", "value": [WEEKNOTE_LINK]}]

        assert overview_to_author_blocks(internal) == [
            {"type": "unsupported", "value": {"stored_type": "weeknote_links", "position": "overview.0"}}
        ]

    @override_settings(CAST_POST_BODY_BLOCKS={"overview": ["tests.custom_post_body_blocks.raising_to_python_block"]})
    def test_malformed_stored_custom_block_is_placeholder(self):
        internal = [{"type": "raising_custom", "value": "boom"}]

        assert overview_to_author_blocks(internal) == [
            {"type": "unsupported", "value": {"stored_type": "raising_custom", "position": "overview.0"}}
        ]

    @override_settings(CAST_POST_BODY_BLOCKS={"overview": ["tests.custom_post_body_blocks.weeknote_links_block"]})
    def test_invalid_stored_custom_block_is_placeholder(self):
        invalid_link = {**WEEKNOTE_LINK, "title": "", "url": "not-a-url"}
        internal = [{"type": "weeknote_links", "value": [{"type": "item", "value": invalid_link, "id": "abc"}]}]

        assert overview_to_author_blocks(internal) == [
            {"type": "unsupported", "value": {"stored_type": "weeknote_links", "position": "overview.0"}}
        ]

    @override_settings(CAST_POST_BODY_BLOCKS={"detail": ["tests.custom_post_body_blocks.detail_weeknote_links_block"]})
    def test_detail_custom_block_serializes_only_in_detail_section(self):
        internal = [{"type": "weeknote_links", "value": [{"type": "item", "value": WEEKNOTE_LINK, "id": "abc"}]}]

        assert section_to_author_blocks(internal, path_prefix="detail") == [
            {"type": "weeknote_links", "value": [WEEKNOTE_LINK]}
        ]
        assert overview_to_author_blocks(internal) == [
            {"type": "unsupported", "value": {"stored_type": "weeknote_links", "position": "overview.0"}}
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
                {"type": "paragraph", "value": "<h2>Inserted above</h2>"},
                {"type": "unsupported", "value": {"stored_type": "embed", "position": "overview.0"}},
            ],
            user=superuser,
            existing_section=existing,
        )
        assert moved == [{"type": "paragraph", "value": "<h2>Inserted above</h2>"}, existing[0]]

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
                {"type": "paragraph", "value": "<h2>Notes</h2>"},
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
        assert data["previous_revision_id"] is None
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

    def test_parent_disappearing_before_transactional_lock_is_not_found(
        self, api_client, blog, admin_user, monkeypatch
    ):
        from wagtail.models import Page

        class MissingParentQuery:
            def update(self, **kwargs):
                assert set(kwargs) == {"numchild"}
                return 0

        monkeypatch.setattr(Page.objects, "filter", lambda **kwargs: MissingParentQuery())
        api_client.force_authenticate(user=admin_user)

        response = api_client.post(
            reverse("cast:api:editor_post_create"),
            self._payload(blog, slug="parent-race"),
            format="json",
        )

        assert response.status_code == 404
        assert response.json() == {"code": "not_found", "detail": "Post parent not found."}

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

    def test_inline_image_not_choosable_by_caller_is_rejected(self, api_client, blog, image):
        # This caller can add the post but lacks image ``choose`` permission, so a real
        # image id is rejected with the same not_found path as a missing image (media IDOR guard).
        caller = page_permission_user(codenames=("add_page",))
        grant_wagtail_admin_access(caller)
        api_client.force_authenticate(user=caller)
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
        assert second.json()["errors"]["slug"][0]["code"] == "duplicate"

    def test_create_uses_latest_draft_slug_for_uniqueness(self, api_client, blog, admin_user):
        existing = PostFactory(
            parent=blog,
            owner=admin_user,
            title="Existing post",
            slug="post-stored-slug",
            live=False,
        )
        draft = existing.get_latest_revision_as_object()
        draft.slug = "post-latest-draft-slug"
        draft.save_revision(user=admin_user)
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_create")

        vacated = api_client.post(
            url,
            self._payload(blog, title="Vacated slug", slug="post-stored-slug"),
            format="json",
        )
        occupied = api_client.post(
            url,
            self._payload(blog, title="Occupied slug", slug="post-latest-draft-slug"),
            format="json",
        )

        assert vacated.status_code == 201, vacated.content
        assert occupied.status_code == 400
        assert occupied.json()["errors"]["slug"][0]["code"] == "duplicate"

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
            overview=[{"type": "paragraph", "value": "<h2>Audio</h2>"}, {"type": "audio", "value": {"id": audio.id}}],
        )
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 201, response.content
        post = Post.objects.get(id=response.json()["id"])
        overview = post.body[0].value.raw_data
        assert any(b["type"] == "audio" and b["value"] == audio.id for b in overview)

    def test_cover_image_not_choosable_is_rejected(self, api_client, blog, image):
        # This caller can add the post but cannot choose the image.
        caller = page_permission_user(codenames=("add_page",))
        grant_wagtail_admin_access(caller)
        api_client.force_authenticate(user=caller)
        url = reverse("cast:api:editor_post_create")
        payload = self._payload(blog, slug="weeknotes-badcover", cover_image={"id": image.id, "alt_text": "x"})
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 400
        assert response.json()["errors"]["cover_image.id"][0]["code"] == "not_found"
