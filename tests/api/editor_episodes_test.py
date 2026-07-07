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


class TestEditorEpisodeCreate:
    pytestmark = pytest.mark.django_db

    # ``admin_user`` can add/edit pages anywhere under the site. Media-negative tests
    # use a fresh page-permission user with no collection media permissions.

    def _payload(self, podcast, **overrides):
        payload = {
            "parent": {"id": podcast.id},
            "title": "Episode 12",
            "slug": "episode-12",
            "tags": ["podcast"],
            "overview": [
                {"type": "paragraph", "value": "<h2>Show notes</h2>"},
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
            "overview": [{"type": "paragraph", "value": "<h2>Notes</h2>"}],
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
        assert data["overview"] == [{"type": "paragraph", "value": "<h2>Notes</h2>"}]

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
            "overview": [{"type": "paragraph", "value": "<h2>Notes</h2>"}],
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

    def test_patch_accepts_if_match_revision_token(self, api_client, podcast, admin_user):
        created = self._create(api_client, podcast, admin_user)
        url = reverse("cast:api:editor_episode_detail", kwargs={"pk": created["id"]})

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

    def test_patch_rejects_mismatched_if_match_and_body_revision(self, api_client, podcast, admin_user):
        created = self._create(api_client, podcast, admin_user)
        url = reverse("cast:api:editor_episode_detail", kwargs={"pk": created["id"]})

        response = api_client.patch(
            url,
            {"base_revision_id": created["latest_revision_id"], "title": "Mismatch"},
            format="json",
            HTTP_IF_MATCH=f'"{created["latest_revision_id"] + 1}"',
        )

        assert response.status_code == 400
        assert response.json()["errors"]["If-Match"][0]["code"] == "mismatch"

    @pytest.mark.parametrize("if_match", ["123", '"²"'])
    def test_patch_rejects_malformed_if_match_revision_token(self, api_client, podcast, admin_user, if_match):
        created = self._create(api_client, podcast, admin_user)
        url = reverse("cast:api:editor_episode_detail", kwargs={"pk": created["id"]})

        response = api_client.patch(
            url,
            {"title": "Malformed header"},
            format="json",
            HTTP_IF_MATCH=if_match,
        )

        assert response.status_code == 400
        assert response.json()["errors"]["If-Match"][0]["code"] == "invalid"

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

    def test_stale_if_match_revision_returns_conflict(self, api_client, podcast, admin_user):
        created = self._create(api_client, podcast, admin_user)
        episode = Episode.objects.get(id=created["id"])
        human_draft = episode.get_latest_revision_as_object()
        human_draft.title = "Human draft"
        human_revision = human_draft.save_revision(user=admin_user)

        url = reverse("cast:api:editor_episode_detail", kwargs={"pk": created["id"]})
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
            "overview": [{"type": "paragraph", "value": "<h2>Notes</h2>"}],
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
