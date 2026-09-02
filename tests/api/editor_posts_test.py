# ruff: noqa: F401,F811,I001
import json
import subprocess
import threading
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.models import Group, Permission
from django.db import close_old_connections, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.test import APIClient
from wagtail.models import Collection, GroupCollectionPermission, GroupPagePermission, Page, Revision

from cast import media_probe
from cast.api.editor import media as editor_media
from cast.api.editor import views as editor_views
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


class TestEditorPostLookup:
    pytestmark = pytest.mark.django_db

    def _url(self, parent_id, slug):
        return reverse("cast:api:editor_post_create") + f"?parent={parent_id}&slug={slug}"

    def test_requires_authentication(self, api_client, blog):
        response = api_client.get(self._url(blog.id, "weeknotes"))

        assert response.status_code in (401, 403)

    def test_requires_wagtail_admin_access(self, api_client, blog):
        user = page_permission_user(codenames=("change_page",))
        api_client.force_authenticate(user=user)

        response = api_client.get(self._url(blog.id, "weeknotes"))

        assert response.status_code == 403
        assert response.json()["code"] == "permission_denied"

    @pytest.mark.parametrize(
        ("query", "field"),
        [
            ("slug=weeknotes", "parent"),
            ("parent=not-an-id&slug=weeknotes", "parent"),
            ("parent=0&slug=weeknotes", "parent"),
            ("parent=1", "slug"),
            ("parent=1&slug=not%20a%20slug", "slug"),
        ],
    )
    def test_rejects_missing_or_malformed_filters(self, api_client, admin_user, query, field):
        api_client.force_authenticate(user=admin_user)

        response = api_client.get(reverse("cast:api:editor_post_create") + f"?{query}")

        assert response.status_code == 400
        assert response.json()["code"] == "validation_error"
        assert field in response.json()["errors"]

    @pytest.mark.parametrize(
        "query",
        [
            "parent=1&parent=2&slug=weeknotes",
            "parent=1&slug=one&slug=two",
            "parent=1&slug=weeknotes&search=extra",
        ],
    )
    def test_rejects_duplicate_or_unknown_filters(self, api_client, admin_user, query):
        api_client.force_authenticate(user=admin_user)

        response = api_client.get(reverse("cast:api:editor_post_create") + f"?{query}")

        assert response.status_code == 400
        assert response.json()["code"] == "validation_error"

    @pytest.mark.parametrize("parent_id", [999999, None])
    def test_unknown_parent_or_no_match_returns_404(self, api_client, blog, admin_user, parent_id):
        api_client.force_authenticate(user=admin_user)
        parent_id = blog.id if parent_id is None else parent_id

        response = api_client.get(self._url(parent_id, "missing-post"))

        assert response.status_code == 404
        assert response.json() == {"code": "not_found", "detail": "Post not found."}

    def test_returns_normal_editor_shape_for_exact_draft(self, api_client, blog, admin_user):
        api_client.force_authenticate(user=admin_user)
        create_response = api_client.post(
            reverse("cast:api:editor_post_create"),
            {
                "parent": {"id": blog.id},
                "title": "Lookup draft",
                "slug": "lookup-draft",
                "tags": ["weeknotes"],
                "overview": [{"type": "paragraph", "value": "<p>Draft.</p>"}],
            },
            format="json",
        )
        assert create_response.status_code == 201, create_response.content

        response = api_client.get(self._url(blog.id, "lookup-draft"))

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == create_response.json()["id"]
        assert data["type"] == "cast.Post"
        assert data["parent"] == {"id": blog.id}
        assert data["slug"] == "lookup-draft"
        assert data["overview"] == [{"type": "paragraph", "value": "<p>Draft.</p>"}]
        assert data["latest_revision_id"] == create_response.json()["latest_revision_id"]
        assert data["previous_revision_id"] == create_response.json()["previous_revision_id"]
        assert data["live"] is False
        assert data["status"] == "draft"

    def test_returns_latest_unpublished_revision_of_live_post(self, api_client, blog, admin_user):
        post = PostFactory(parent=blog, owner=admin_user, title="Live title", slug="live-with-draft")
        draft = post.get_latest_revision_as_object()
        draft.title = "Unpublished title"
        revision = draft.save_revision(user=admin_user)
        api_client.force_authenticate(user=admin_user)

        response = api_client.get(self._url(blog.id, "live-with-draft"))

        assert response.status_code == 200
        assert response.json()["title"] == "Unpublished title"
        assert response.json()["latest_revision_id"] == revision.id
        assert response.json()["live"] is True
        assert response.json()["status"] == "draft"

    def test_lookup_matches_latest_unpublished_slug_not_materialized_slug(self, api_client, blog, admin_user):
        post = PostFactory(parent=blog, owner=admin_user, title="Original", slug="original-slug", live=False)
        draft = post.get_latest_revision_as_object()
        draft.slug = "latest-draft-slug"
        draft.save_revision(user=admin_user)
        api_client.force_authenticate(user=admin_user)

        old_response = api_client.get(self._url(blog.id, "original-slug"))
        new_response = api_client.get(self._url(blog.id, "latest-draft-slug"))

        assert old_response.status_code == 404
        assert new_response.status_code == 200
        assert new_response.json()["id"] == post.id
        assert new_response.json()["slug"] == "latest-draft-slug"

    def test_lookup_rejects_ambiguous_latest_draft_slug(self, api_client, blog, admin_user):
        for stored_slug in ("stored-one", "stored-two"):
            post = PostFactory(parent=blog, owner=admin_user, title=stored_slug, slug=stored_slug, live=False)
            draft = post.get_latest_revision_as_object()
            draft.slug = "shared-draft-slug"
            draft.save_revision(user=admin_user)
        api_client.force_authenticate(user=admin_user)

        response = api_client.get(self._url(blog.id, "shared-draft-slug"))

        assert response.status_code == 409
        assert response.json()["code"] == "ambiguous_lookup"

    def test_scopes_lookup_to_exact_direct_parent(self, api_client, blog, admin_user):
        other_blog = BlogFactory(parent=blog.get_parent(), owner=admin_user, slug="other-blog")
        post = PostFactory(parent=other_blog, owner=admin_user, title="Other post", slug="same-slug")
        nested = Post(title="Nested", slug="nested-post", owner=admin_user)
        post.add_child(instance=nested)
        non_post = Page(title="Not a post", slug="not-a-post", owner=admin_user)
        blog.add_child(instance=non_post)
        api_client.force_authenticate(user=admin_user)

        for slug in ("same-slug", "nested-post", "not-a-post"):
            response = api_client.get(self._url(blog.id, slug))
            assert response.status_code == 404

    def test_slug_match_is_case_sensitive(self, api_client, blog, admin_user):
        PostFactory(parent=blog, owner=admin_user, title="Exact case", slug="Exact-Case")
        api_client.force_authenticate(user=admin_user)

        response = api_client.get(self._url(blog.id, "exact-case"))

        assert response.status_code == 404

    def test_matching_post_requires_edit_permission(self, api_client, blog, admin_user):
        PostFactory(parent=blog, owner=admin_user, title="Private draft", slug="private-draft")
        stranger = UserFactory()
        grant_wagtail_admin_access(stranger)
        api_client.force_authenticate(user=stranger)

        response = api_client.get(self._url(blog.id, "private-draft"))

        assert response.status_code == 403
        assert response.json()["code"] == "permission_denied"


class TestEditorPostDetail:
    pytestmark = pytest.mark.django_db

    def _create(self, api_client, blog, admin_user):
        api_client.force_authenticate(user=admin_user)
        create_url = reverse("cast:api:editor_post_create")
        payload = {
            "parent": {"id": blog.id},
            "title": "Readable draft",
            "slug": "readable-draft",
            "seo_title": "Readable draft for search",
            "search_description": "A concise description for search and social previews.",
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
        assert data["seo_title"] == "Readable draft for search"
        assert data["search_description"] == "A concise description for search and social previews."
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

    def test_draft_only_patch_locks_and_accepts_unpublished_post(self, api_client, blog, admin_user, mocker):
        created = self._create(api_client, blog, admin_user)
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})
        lock = mocker.patch.object(Post.objects, "select_for_update", wraps=Post.objects.select_for_update)

        response = api_client.patch(
            url,
            {
                "base_revision_id": created["latest_revision_id"],
                "require_unpublished": True,
                "title": "Still a draft",
            },
            format="json",
        )

        assert response.status_code == 200, response.content
        assert response.json()["live"] is False
        assert response.json()["title"] == "Still a draft"
        lock.assert_called_once_with()

    def test_slug_patch_locks_parent_and_handles_disappearance(self, api_client, blog, admin_user, monkeypatch):
        created = self._create(api_client, blog, admin_user)

        class MissingParentQuery:
            def update(self, **kwargs):
                assert set(kwargs) == {"numchild"}
                return 0

        monkeypatch.setattr(Page.objects, "filter", lambda **kwargs: MissingParentQuery())
        response = api_client.patch(
            reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]}),
            {
                "base_revision_id": created["latest_revision_id"],
                "slug": "serialized-post-slug",
            },
            format="json",
        )

        assert response.status_code == 404
        assert response.json() == {"code": "not_found", "detail": "Post parent not found."}
        assert Post.objects.get(pk=created["id"]).latest_revision_id == created["latest_revision_id"]

    def test_draft_only_patch_rejects_post_published_before_row_lock(self, api_client, blog, admin_user):
        created = self._create(api_client, blog, admin_user)
        post = Post.objects.get(pk=created["id"]).specific
        post.get_latest_revision().publish(user=admin_user)
        post.refresh_from_db()
        revision_id = post.latest_revision_id
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})

        response = api_client.patch(
            url,
            {
                "base_revision_id": revision_id,
                "require_unpublished": True,
                "title": "Must not be written",
            },
            format="json",
        )

        assert response.status_code == 409
        assert response.json()["code"] == "published_post"
        post.refresh_from_db()
        assert post.latest_revision_id == revision_id
        assert post.get_latest_revision_as_object().title != "Must not be written"

    def test_scheduled_post_is_reported_and_rejected_by_draft_only_patch(self, api_client, blog, admin_user):
        created = self._create(api_client, blog, admin_user)
        post = Post.objects.get(pk=created["id"]).specific
        scheduled = post.get_latest_revision_as_object()
        scheduled.go_live_at = timezone.now() + timedelta(days=1)
        scheduled_revision = scheduled.save_revision(user=admin_user)
        scheduled_revision.publish(user=admin_user)
        scheduled_revision.refresh_from_db()
        assert scheduled_revision.approved_go_live_at is not None

        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})
        api_client.force_authenticate(user=admin_user)
        detail = api_client.get(url, format="json")
        response = api_client.patch(
            url,
            {
                "base_revision_id": scheduled_revision.id,
                "require_unpublished": True,
                "title": "Must not replace the schedule",
            },
            format="json",
        )

        assert detail.status_code == 200
        assert detail.json()["status"] == "scheduled"
        assert detail.json()["live"] is False
        assert response.status_code == 409
        assert response.json()["code"] == "scheduled_post"
        post.refresh_from_db()
        assert post.latest_revision_id == scheduled_revision.id
        assert post.get_latest_revision_as_object().title != "Must not replace the schedule"

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.skipif(connection.vendor != "postgresql", reason="PostgreSQL row-lock semantics")
    def test_postgres_schedule_approval_serializes_with_draft_only_patch(
        self, api_client, blog, admin_user, monkeypatch
    ):
        created = self._create(api_client, blog, admin_user)
        revision_id = created["latest_revision_id"]
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})
        revisions_locked = threading.Event()
        release_patch = threading.Event()
        schedule_update_started = threading.Event()
        schedule_update_finished = threading.Event()
        thread_errors = []
        responses = []
        original_schedule_check = editor_views.PostEditorMixin._has_approved_schedule

        def pause_after_revision_locks(post, *, for_update=False):
            scheduled = original_schedule_check(post, for_update=for_update)
            if for_update:
                revisions_locked.set()
                assert release_patch.wait(timeout=5)
            return scheduled

        monkeypatch.setattr(
            editor_views.PostEditorMixin,
            "_has_approved_schedule",
            staticmethod(pause_after_revision_locks),
        )

        def patch_draft():
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(user=type(admin_user).objects.get(pk=admin_user.pk))
                responses.append(
                    client.patch(
                        url,
                        {
                            "base_revision_id": revision_id,
                            "require_unpublished": True,
                            "title": "Serialized draft update",
                        },
                        format="json",
                    )
                )
            except Exception as exc:  # pragma: no cover - surfaced by the assertion below
                thread_errors.append(exc)
            finally:
                close_old_connections()

        def approve_existing_revision():
            close_old_connections()
            try:
                assert revisions_locked.wait(timeout=5)
                with transaction.atomic():
                    revision = Revision.objects.get(pk=revision_id)
                    revision.approved_go_live_at = timezone.now() + timedelta(days=1)
                    schedule_update_started.set()
                    revision.save(update_fields=["approved_go_live_at"])
                schedule_update_finished.set()
            except Exception as exc:  # pragma: no cover - surfaced by the assertion below
                thread_errors.append(exc)
            finally:
                close_old_connections()

        patch_thread = threading.Thread(target=patch_draft)
        schedule_thread = threading.Thread(target=approve_existing_revision)
        patch_thread.start()
        assert revisions_locked.wait(timeout=5)
        schedule_thread.start()
        assert schedule_update_started.wait(timeout=5)
        assert not schedule_update_finished.wait(timeout=0.25)
        release_patch.set()
        patch_thread.join(timeout=5)
        schedule_thread.join(timeout=5)

        assert not patch_thread.is_alive() and not schedule_thread.is_alive()
        assert thread_errors == []
        assert responses[0].status_code == 200, responses[0].content
        assert schedule_update_finished.is_set()
        assert Revision.objects.get(pk=revision_id).approved_go_live_at is not None

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

    def test_draft_rename_vacates_slug_for_another_draft(self, api_client, blog, admin_user):
        draft_a = self._create(api_client, blog, admin_user, title="Draft A", slug="draft-slug-x")
        draft_b = self._create(api_client, blog, admin_user, title="Draft B", slug="draft-slug-b")
        url_a = reverse("cast:api:editor_post_detail", kwargs={"pk": draft_a["id"]})
        url_b = reverse("cast:api:editor_post_detail", kwargs={"pk": draft_b["id"]})

        renamed_a = api_client.patch(
            url_a,
            {
                "base_revision_id": draft_a["latest_revision_id"],
                "require_unpublished": True,
                "slug": "draft-slug-y",
            },
            format="json",
        )
        renamed_b = api_client.patch(
            url_b,
            {
                "base_revision_id": draft_b["latest_revision_id"],
                "require_unpublished": True,
                "slug": "draft-slug-x",
            },
            format="json",
        )

        assert renamed_a.status_code == 200, renamed_a.content
        assert renamed_b.status_code == 200, renamed_b.content
        assert renamed_a.json()["slug"] == "draft-slug-y"
        assert renamed_a.json()["page_slug"] == "draft-slug-y"
        assert renamed_b.json()["slug"] == "draft-slug-x"
        assert renamed_b.json()["page_slug"] == "draft-slug-x"
        stored_a = Post.objects.get(pk=draft_a["id"])
        stored_b = Post.objects.get(pk=draft_b["id"])
        assert (stored_a.slug, stored_b.slug) == ("draft-slug-y", "draft-slug-x")
        assert stored_a.url_path.endswith("/draft-slug-y/")
        assert stored_b.url_path.endswith("/draft-slug-x/")
        assert stored_a.live is stored_b.live is False

    def test_unpublished_page_slug_rolls_back_if_revision_save_fails(self, api_client, blog, admin_user, monkeypatch):
        created = self._create(api_client, blog, admin_user, slug="before-rollback")
        original_save_revision = Post.save_revision

        def fail_renamed_revision(page, *args, **kwargs):
            if page.pk == created["id"] and page.slug == "after-rollback":
                raise RuntimeError("revision write failed")
            return original_save_revision(page, *args, **kwargs)

        monkeypatch.setattr(Post, "save_revision", fail_renamed_revision)

        with pytest.raises(RuntimeError, match="revision write failed"):
            api_client.patch(
                reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]}),
                {
                    "base_revision_id": created["latest_revision_id"],
                    "require_unpublished": True,
                    "slug": "after-rollback",
                },
                format="json",
            )

        persisted = Post.objects.get(pk=created["id"])
        assert persisted.slug == "before-rollback"
        assert persisted.latest_revision_id == created["latest_revision_id"]

    def test_patch_rejects_slug_used_by_siblings_latest_draft(self, api_client, blog, admin_user):
        sibling = self._create(api_client, blog, admin_user, title="Sibling", slug="sibling-stored-slug")
        candidate = self._create(api_client, blog, admin_user, title="Candidate", slug="candidate-slug")
        sibling_url = reverse("cast:api:editor_post_detail", kwargs={"pk": sibling["id"]})
        candidate_url = reverse("cast:api:editor_post_detail", kwargs={"pk": candidate["id"]})
        sibling_rename = api_client.patch(
            sibling_url,
            {
                "base_revision_id": sibling["latest_revision_id"],
                "slug": "sibling-latest-draft-slug",
            },
            format="json",
        )
        assert sibling_rename.status_code == 200, sibling_rename.content
        assert Post.objects.get(pk=sibling["id"]).slug == "sibling-latest-draft-slug"

        response = api_client.patch(
            candidate_url,
            {
                "base_revision_id": candidate["latest_revision_id"],
                "slug": "sibling-latest-draft-slug",
            },
            format="json",
        )

        assert response.status_code == 400
        assert response.json()["errors"]["slug"][0]["code"] == "duplicate"
        assert Post.objects.get(pk=candidate["id"]).latest_revision_id == candidate["latest_revision_id"]

    def test_live_slug_and_unpublished_rename_slug_are_both_reserved(self, api_client, blog, admin_user):
        live_post = PostFactory(
            parent=blog,
            owner=admin_user,
            title="Live sibling",
            slug="live-public-slug",
        )
        live_draft = live_post.get_latest_revision_as_object()
        live_draft.slug = "live-unpublished-rename"
        live_draft.save_revision(user=admin_user)
        candidate = self._create(api_client, blog, admin_user, title="Candidate", slug="live-candidate")
        candidate_url = reverse("cast:api:editor_post_detail", kwargs={"pk": candidate["id"]})

        for reserved_slug in ("live-public-slug", "live-unpublished-rename"):
            response = api_client.patch(
                candidate_url,
                {
                    "base_revision_id": candidate["latest_revision_id"],
                    "slug": reserved_slug,
                },
                format="json",
            )

            assert response.status_code == 400
            assert response.json()["errors"]["slug"][0]["code"] == "duplicate"

        live_post.refresh_from_db()
        assert live_post.live is True
        assert live_post.slug == "live-public-slug"
        assert live_post.get_latest_revision_as_object().slug == "live-unpublished-rename"
        assert Post.objects.get(pk=candidate["id"]).latest_revision_id == candidate["latest_revision_id"]

    def test_live_page_patch_keeps_public_page_slug_until_publish(self, api_client, blog, admin_user):
        live_post = PostFactory(
            parent=blog,
            owner=admin_user,
            title="Live post",
            slug="live-public-slug",
        )
        revision = live_post.save_revision(user=admin_user, changed=False)
        api_client.force_authenticate(user=admin_user)

        response = api_client.patch(
            reverse("cast:api:editor_post_detail", kwargs={"pk": live_post.id}),
            {
                "base_revision_id": revision.id,
                "slug": "live-draft-rename",
            },
            format="json",
        )

        assert response.status_code == 200, response.content
        assert response.json()["slug"] == "live-draft-rename"
        assert response.json()["page_slug"] == "live-public-slug"
        live_post.refresh_from_db()
        assert live_post.slug == "live-public-slug"

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
        assert data["previous_revision_id"] == created["latest_revision_id"]
        assert data["title"] == "Retitled draft"
        assert data["slug"] == "editable-draft"
        assert data["tags"] == ["weeknotes"]
        assert data["overview"] == [
            {"type": "paragraph", "value": "<h2>Notes</h2>"},
            {"type": "paragraph", "value": "<p>Original text.</p>"},
        ]
        assert data["live"] is False

    def test_patch_predecessor_is_relative_to_the_exact_serialized_revision(
        self, api_client, blog, admin_user, monkeypatch
    ):
        from cast.api.editor.views import PostEditorMixin

        created = self._create(api_client, blog, admin_user, slug="exact-response-revision")
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})
        original_serialize = PostEditorMixin._serialize
        later_revision_ids = []

        def serialize_after_later_revision(self, post, *, user, content_post=None, revision=None):
            assert revision is not None
            later_draft = post.get_latest_revision_as_object()
            later_draft.title = "Later same-page revision"
            later_revision_ids.append(later_draft.save_revision(user=user).id)
            return original_serialize(
                self,
                post,
                user=user,
                content_post=content_post,
                revision=revision,
            )

        monkeypatch.setattr(PostEditorMixin, "_serialize", serialize_after_later_revision)

        response = api_client.patch(
            url,
            {"base_revision_id": created["latest_revision_id"], "title": "Serialized update"},
            format="json",
        )

        assert response.status_code == 200, response.content
        data = response.json()
        assert data["title"] == "Serialized update"
        assert data["latest_revision_id"] != later_revision_ids[0]
        assert data["previous_revision_id"] == created["latest_revision_id"]
        assert Post.objects.get(pk=created["id"]).latest_revision_id == later_revision_ids[0]

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
                "seo_title": "Updated search title",
                "search_description": "Updated search and social description.",
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
        assert data["page_slug"] == "updated-draft"
        assert data["seo_title"] == "Updated search title"
        assert data["search_description"] == "Updated search and social description."
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
        assert detail["seo_title"] == "Updated search title"
        assert detail["search_description"] == "Updated search and social description."
        assert detail["tags"] == ["weeknotes", "updated"]
        assert detail["categories"] == [category.id]
        assert detail["cover_image"] == {"id": image.id, "alt_text": "Updated alt"}
        assert detail["overview"] == overview

        revision_post = Post.objects.get(id=created["id"]).get_latest_revision().as_object()
        assert revision_post.seo_title == "Updated search title"
        assert revision_post.search_description == "Updated search and social description."
        assert [tag.name for tag in revision_post.tags.all()] == ["weeknotes", "updated"]
        assert [saved_category.pk for saved_category in revision_post.categories.all()] == [category.id]
        assert revision_post.cover_image_id == image.id

        stored_post = Post.objects.get(id=created["id"])
        assert stored_post.title == "Editable draft"
        assert stored_post.slug == "updated-draft"
        assert stored_post.cover_image_id is None

    def test_patch_can_clear_promote_text(self, api_client, blog, admin_user):
        created = self._create(api_client, blog, admin_user, slug="clear-promote")
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})

        response = api_client.patch(
            url,
            {
                "base_revision_id": created["latest_revision_id"],
                "seo_title": "",
                "search_description": "",
            },
            format="json",
        )

        assert response.status_code == 200, response.content
        assert response.json()["seo_title"] == ""
        assert response.json()["search_description"] == ""
        detail = api_client.get(url, format="json").json()
        assert detail["seo_title"] == ""
        assert detail["search_description"] == ""

    def test_patch_rejects_overlong_seo_title(self, api_client, blog, admin_user):
        created = self._create(api_client, blog, admin_user, slug="long-promote-title")
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})

        response = api_client.patch(
            url,
            {"base_revision_id": created["latest_revision_id"], "seo_title": "x" * 256},
            format="json",
        )

        assert response.status_code == 400
        assert response.json()["errors"]["seo_title"][0]["code"] == "max_length"

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
        assert data["previous_revision_id"] == first["latest_revision_id"]

    def test_revision_predecessor_is_page_scoped_with_global_revisions_interleaved(self, api_client, blog, admin_user):
        created = self._create(api_client, blog, admin_user, slug="page-revision-order")
        target_url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})
        unrelated = PostFactory(
            parent=blog,
            owner=admin_user,
            title="Unrelated revisions",
            slug="unrelated-revisions",
            live=False,
        )
        unrelated.save_revision(user=admin_user)

        first = api_client.patch(
            target_url,
            {"base_revision_id": created["latest_revision_id"], "title": "First target update"},
            format="json",
        ).json()
        unrelated.save_revision(user=admin_user)
        second_response = api_client.patch(
            target_url,
            {"base_revision_id": first["latest_revision_id"], "title": "Second target update"},
            format="json",
        )

        assert second_response.status_code == 200, second_response.content
        second = second_response.json()
        assert second["previous_revision_id"] == first["latest_revision_id"]
        assert second["previous_revision_id"] != second["latest_revision_id"] - 1

        detail = api_client.get(target_url).json()
        lookup_url = reverse("cast:api:editor_post_create") + f"?parent={blog.id}&slug=page-revision-order"
        lookup = api_client.get(lookup_url).json()
        assert (detail["latest_revision_id"], detail["previous_revision_id"]) == (
            second["latest_revision_id"],
            first["latest_revision_id"],
        )
        assert (lookup["latest_revision_id"], lookup["previous_revision_id"]) == (
            detail["latest_revision_id"],
            detail["previous_revision_id"],
        )

    def test_revision_predecessor_uses_wagtail_timestamp_then_primary_key_order(self, api_client, blog, admin_user):
        created = self._create(api_client, blog, admin_user, slug="page-revision-chronology")
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
        ).json()
        post = Post.objects.get(pk=created["id"])
        now = timezone.now()
        post.revisions.filter(pk=created["latest_revision_id"]).update(created_at=now - timedelta(days=1))
        post.revisions.filter(pk=first["latest_revision_id"]).update(created_at=now - timedelta(days=2))
        post.revisions.filter(pk=second["latest_revision_id"]).update(created_at=now)

        detail = api_client.get(url)

        assert detail.status_code == 200, detail.content
        assert detail.json()["latest_revision_id"] == second["latest_revision_id"]
        assert detail.json()["previous_revision_id"] == created["latest_revision_id"]
        assert created["latest_revision_id"] < first["latest_revision_id"]

    def test_revision_predecessor_uses_one_id_only_query(self, api_client, blog, admin_user):
        created = self._create(api_client, blog, admin_user, slug="page-revision-query-shape")
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})
        updated = api_client.patch(
            url,
            {"base_revision_id": created["latest_revision_id"], "title": "Updated"},
            format="json",
        ).json()
        post = Post.objects.get(pk=created["id"])

        with CaptureQueriesContext(connection) as queries:
            predecessor = editor_views._previous_page_revision_id(post, updated["latest_revision_id"])

        assert predecessor == created["latest_revision_id"]
        assert len(queries) == 1
        selected_columns = queries[0]["sql"].upper().partition(" FROM ")[0]
        assert '"CONTENT"' not in selected_columns

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
