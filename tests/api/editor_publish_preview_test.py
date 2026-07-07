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


class _FakeScopedToken:
    def __init__(self, scope: str):
        self.scope = scope


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
                {"type": "paragraph", "value": "<h2>Notes</h2>"},
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
            body=json.dumps([{"type": "overview", "value": [{"type": "paragraph", "value": "<h2>Live</h2>"}]}]),
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
            body=json.dumps([{"type": "overview", "value": [{"type": "paragraph", "value": "<h2>Live</h2>"}]}]),
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


class TestEditorPreview:
    pytestmark = pytest.mark.django_db

    def _post_with_live_and_draft_revisions(self, blog, admin_user):
        post = PostFactory(
            owner=blog.owner,
            parent=blog,
            title="Live preview title",
            slug="live-preview-title",
            body=json.dumps([{"type": "overview", "value": [{"type": "paragraph", "value": "<h2>Live-only marker</h2>"}]}]),
        )
        post.save_revision(user=admin_user, changed=False)
        draft = post.get_latest_revision_as_object()
        draft.title = "Draft preview title"
        draft.body = json.dumps([{"type": "overview", "value": [{"type": "paragraph", "value": "<h2>Draft-only marker</h2>"}]}])
        draft.save_revision(user=admin_user)
        post.refresh_from_db()
        assert post.live is True
        assert post.has_unpublished_changes is True
        return post

    def _episode_with_live_and_draft_revisions(self, podcast, admin_user):
        episode = EpisodeFactory(
            owner=podcast.owner,
            parent=podcast,
            title="Live episode title",
            slug="live-episode-preview",
            body=json.dumps([{"type": "overview", "value": [{"type": "paragraph", "value": "<h2>Live episode marker</h2>"}]}]),
        )
        episode.save_revision(user=admin_user, changed=False)
        draft = episode.get_latest_revision_as_object()
        draft.title = "Draft episode title"
        draft.body = json.dumps(
            [{"type": "overview", "value": [{"type": "paragraph", "value": "<h2>Draft episode marker</h2>"}]}]
        )
        draft.save_revision(user=admin_user)
        episode.refresh_from_db()
        assert episode.live is True
        assert episode.has_unpublished_changes is True
        return episode

    def test_post_preview_renders_latest_draft_as_html(self, api_client, blog, admin_user):
        post = self._post_with_live_and_draft_revisions(blog, admin_user)
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_preview", kwargs={"pk": post.id})

        response = api_client.get(url)

        assert response.status_code == 200, response.content
        assert response.headers["Content-Type"].startswith("text/html")
        html = response.content.decode()
        assert "Draft preview title" in html
        assert "Draft-only marker" in html
        assert "Live-only marker" not in html

    def test_post_preview_allows_scoped_token_without_write_scope(self, api_client, blog, admin_user):
        post = self._post_with_live_and_draft_revisions(blog, admin_user)
        api_client.force_authenticate(user=admin_user, token=_FakeScopedToken("publish"))
        url = reverse("cast:api:editor_post_preview", kwargs={"pk": post.id})

        response = api_client.get(url)

        assert response.status_code == 200, response.content

    def test_post_preview_missing_post_uses_editor_envelope(self, api_client, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_preview", kwargs={"pk": 999999})

        response = api_client.get(url)

        assert response.status_code == 404
        assert response.headers["Content-Type"].startswith("application/json")
        assert response.json() == {"code": "not_found", "detail": "Post not found."}

    def test_post_preview_requires_authentication(self, api_client, post):
        url = reverse("cast:api:editor_post_preview", kwargs={"pk": post.id})

        response = api_client.get(url)

        assert response.status_code in (401, 403)

    def test_post_preview_requires_edit_permission(self, api_client, post):
        user = UserFactory()
        grant_wagtail_admin_access(user)
        api_client.force_authenticate(user=user)
        url = reverse("cast:api:editor_post_preview", kwargs={"pk": post.id})

        response = api_client.get(url)

        assert response.status_code == 403
        assert response.json() == {"code": "permission_denied", "detail": "You cannot preview this draft."}

    def test_episode_preview_renders_episode_draft(self, api_client, podcast, admin_user):
        episode = self._episode_with_live_and_draft_revisions(podcast, admin_user)
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_episode_preview", kwargs={"pk": episode.id})

        response = api_client.get(url)

        assert response.status_code == 200, response.content
        assert response.headers["Content-Type"].startswith("text/html")
        html = response.content.decode()
        assert "Draft episode title" in html
        assert "Draft episode marker" in html
        assert "Live episode marker" not in html

    def test_episode_preview_requires_authentication(self, api_client, podcast, admin_user):
        episode = self._episode_with_live_and_draft_revisions(podcast, admin_user)
        url = reverse("cast:api:editor_episode_preview", kwargs={"pk": episode.id})

        response = api_client.get(url)

        assert response.status_code in (401, 403)

    def test_episode_preview_requires_edit_permission(self, api_client, podcast, admin_user):
        episode = self._episode_with_live_and_draft_revisions(podcast, admin_user)
        user = UserFactory()
        grant_wagtail_admin_access(user)
        api_client.force_authenticate(user=user)
        url = reverse("cast:api:editor_episode_preview", kwargs={"pk": episode.id})

        response = api_client.get(url)

        assert response.status_code == 403
        assert response.json() == {"code": "permission_denied", "detail": "You cannot preview this draft."}

    def test_episode_preview_rejects_plain_post_id(self, api_client, post, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_episode_preview", kwargs={"pk": post.id})

        response = api_client.get(url)

        assert response.status_code == 404
        assert response.json() == {"code": "not_found", "detail": "Episode not found."}


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
                {"type": "paragraph", "value": "<h2>Detail</h2>"},
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

    def test_create_rejects_heading_block(self, api_client, blog, superuser):
        api_client.force_authenticate(user=superuser)
        create_url = reverse("cast:api:editor_post_create")
        payload = {
            "parent": {"id": blog.id},
            "title": "Heading rejected",
            "slug": "heading-rejected",
            "overview": [{"type": "heading", "value": "Notes"}],
        }

        response = api_client.post(create_url, payload, format="json")

        assert response.status_code == 400
        assert response.json()["errors"]["overview.0.type"][0]["code"] == "unsupported_block_type"

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
                            {"type": "paragraph", "value": "<h2>Old heading</h2>"},
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
        replacement = [detail[0], {"type": "paragraph", "value": "<h2>Replacement</h2>"}]

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
        assert stored_detail[1] == {"type": "paragraph", "value": "<h2>Replacement</h2>"}

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
                "detail": [{"type": "paragraph", "value": "<h2>Inserted above</h2>"}, placeholder],
            },
            format="json",
        )

        assert response.status_code == 200, response.content
        assert response.json()["detail"] == [
            {"type": "paragraph", "value": "<h2>Inserted above</h2>"},
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
                "detail": [{"type": "paragraph", "value": "<h2>Keep editing</h2>"}, *detail],
            },
            format="json",
        )

        assert response.status_code == 200, response.content
        assert response.json()["detail"] == [
            {"type": "paragraph", "value": "<h2>Keep editing</h2>"},
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
