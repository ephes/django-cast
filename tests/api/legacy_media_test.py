# ruff: noqa: F401,F811,I001
import json
from datetime import datetime, timedelta
from urllib.parse import urlencode

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.request import Request
from wagtail.models import PageViewRestriction

from cast import modal_facet_counts
from cast.api.serializers import AudioPodloveSerializer
from cast.api.views import (
    AudioPodloveDetailView,
    CastImagesAPIViewSet,
    FilteredPagesAPIViewSet,
    StandardResultsSetPagination,
    ThemeListView,
)
from cast.devdata import create_transcript, generate_blog_with_media
from cast.models import Audio, Contributor, EpisodeContributor, PostCategory, TranscriptSpeakerMapping

from tests.factories import PostFactory, UserFactory

SCANNER_SEARCH_PAYLOAD = "-9399862) UNION ALL SELECT CONCAT('a','b'),NULL,NULL -- -"


def test_api_root(api_client):
    """Test that the API root returns a 200."""
    url = reverse("cast:api:root")
    r = api_client.get(url)
    assert r.status_code == 200


def test_standard_results_set_pagination_max_page_size():
    assert StandardResultsSetPagination.max_page_size == 200


class TestBlogVideo:
    pytestmark = pytest.mark.django_db

    @classmethod
    def setup_class(cls):
        cls.list_url = reverse("cast:api:video_list")
        cls.detail_url = reverse("cast:api:video_detail", kwargs={"pk": 1})

    def test_video_list_endpoint_without_authentication(self, api_client):
        """Check for not authenticated status code if trying to access the list
        endpoint without being authenticated.
        """
        r = api_client.get(self.list_url, format="json")
        assert r.status_code == 403

    def test_video_detail_endpoint_without_authentication(self, api_client):
        """Check for not authenticated status code if trying to access the
        detail endpoint without being authenticated.
        """
        r = api_client.get(self.detail_url, format="json")
        assert r.status_code == 403

    def test_video_list_endpoint_with_authentication(self, api_client):
        """Check for list result when accessing the list endpoint
        being logged in.
        """
        user = UserFactory()
        api_client.login(username=user.username, password="password")
        r = api_client.get(self.list_url, format="json")
        # dont redirect to login page
        assert r.status_code == 200
        assert "results" in r.json()

    def test_video_detail_endpoint_for_other_user_returns_404(self, api_client, video):
        requester = UserFactory()
        api_client.login(username=requester.username, password="password")

        detail_url = reverse("cast:api:video_detail", kwargs={"pk": video.pk})
        r = api_client.get(detail_url, format="json")

        assert r.status_code == 404

    def test_video_delete_endpoint_for_other_user_returns_404_and_keeps_video(self, api_client, video):
        requester = UserFactory()
        api_client.login(username=requester.username, password="password")

        detail_url = reverse("cast:api:video_detail", kwargs={"pk": video.pk})
        r = api_client.delete(detail_url, format="json")

        assert r.status_code == 404
        assert type(video).objects.filter(pk=video.pk).exists()

    def test_video_delete_endpoint_for_owner_deletes_video(self, api_client, user, video):
        api_client.login(username=user.username, password="password")

        detail_url = reverse("cast:api:video_detail", kwargs={"pk": video.pk})
        r = api_client.delete(detail_url, format="json")

        assert r.status_code == 204
        assert not type(video).objects.filter(pk=video.pk).exists()

    def test_video_detail_endpoint_for_owner_returns_200(self, api_client, user, video):
        api_client.login(username=user.username, password="password")

        detail_url = reverse("cast:api:video_detail", kwargs={"pk": video.pk})
        r = api_client.get(detail_url, format="json")

        assert r.status_code == 200
        assert r.json()["id"] == video.pk

    def test_video_delete_endpoint_without_authentication_returns_403(self, api_client, video):
        detail_url = reverse("cast:api:video_detail", kwargs={"pk": video.pk})
        r = api_client.delete(detail_url, format="json")
        assert r.status_code == 403


class TestBlogAudio:
    pytestmark = pytest.mark.django_db

    @classmethod
    def setup_class(cls):
        cls.list_url = reverse("cast:api:audio_list")
        cls.detail_url = reverse("cast:api:audio_detail", kwargs={"pk": 1})

    def test_audio_list_endpoint_without_authentication(self, api_client):
        """Check for not authenticated status code if trying to access the list
        endpoint without being authenticated.
        """
        r = api_client.get(self.list_url, format="json")
        assert r.status_code == 403

    def test_audio_detail_endpoint_without_authentication(self, api_client):
        """Check for not authenticated status code if trying to access the
        detail endpoint without being authenticated.
        """
        r = api_client.get(self.detail_url, format="json")
        assert r.status_code == 403

    def test_audio_list_endpoint_with_authentication(self, api_client):
        """Check for list result when accessing the list endpoint
        being logged in.
        """
        user = UserFactory()
        api_client.login(username=user.username, password="password")
        r = api_client.get(self.list_url, format="json")
        # dont redirect to login page
        assert r.status_code == 200
        assert "results" in r.json()

    def test_audio_detail_endpoint_for_other_user_returns_404(self, api_client, audio):
        requester = UserFactory()
        api_client.login(username=requester.username, password="password")

        detail_url = reverse("cast:api:audio_detail", kwargs={"pk": audio.pk})
        r = api_client.get(detail_url, format="json")

        assert r.status_code == 404

    def test_audio_delete_endpoint_for_other_user_returns_404_and_keeps_audio(self, api_client, audio):
        requester = UserFactory()
        api_client.login(username=requester.username, password="password")

        detail_url = reverse("cast:api:audio_detail", kwargs={"pk": audio.pk})
        r = api_client.delete(detail_url, format="json")

        assert r.status_code == 404
        assert type(audio).objects.filter(pk=audio.pk).exists()

    def test_audio_delete_endpoint_for_owner_deletes_audio(self, api_client, user, audio):
        api_client.login(username=user.username, password="password")

        detail_url = reverse("cast:api:audio_detail", kwargs={"pk": audio.pk})
        r = api_client.delete(detail_url, format="json")

        assert r.status_code == 204
        assert not type(audio).objects.filter(pk=audio.pk).exists()

    def test_audio_detail_endpoint_for_owner_returns_200(self, api_client, user, audio):
        api_client.login(username=user.username, password="password")

        detail_url = reverse("cast:api:audio_detail", kwargs={"pk": audio.pk})
        r = api_client.get(detail_url, format="json")

        assert r.status_code == 200
        assert r.json()["id"] == audio.pk

    def test_audio_delete_endpoint_without_authentication_returns_403(self, api_client, audio):
        detail_url = reverse("cast:api:audio_detail", kwargs={"pk": audio.pk})
        r = api_client.delete(detail_url, format="json")
        assert r.status_code == 403


class TestPodcastAudio:
    pytestmark = pytest.mark.django_db

    def test_podlove_detail_endpoint_without_authentication(self, api_client, episode):
        """A published episode's podlove config is accessible without authentication."""
        audio = episode.podcast_audio
        podlove_detail_url = reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk})
        r = api_client.get(podlove_detail_url, format="json")
        assert r.status_code == 200

    def test_podlove_detail_endpoint_duration(self, api_client, episode):
        """Test whether microseconds get stripped away from duration via api - they have
        to be for podlove player to work.
        """
        audio = episode.podcast_audio
        delta = timedelta(days=0, hours=1, minutes=10, seconds=20, microseconds=40)
        audio.duration = delta
        audio.save()
        assert "." in str(audio.duration)
        podlove_detail_url = reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk})
        r = api_client.get(podlove_detail_url, format="json")
        assert "." not in r.json()["duration"]

    def test_podlove_detail_endpoint_includes_link_to_episode(self, api_client, episode):
        """Test whether the podlove detail endpoint includes a link to the episode."""
        audio = episode.podcast_audio
        podlove_detail_url = reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk})

        r = api_client.get(podlove_detail_url, format="json")
        assert r.status_code == 200

        # link is always included, might be empty
        assert "link" in r.json()

        # explicitly set episode_id FIXME: only works if there are multiple episodes for audio
        podlove_detail_url_with_episode_id = f"{podlove_detail_url}?episode_id={episode.pk}"

        r = api_client.get(podlove_detail_url_with_episode_id, format="json")
        assert r.status_code == 200

        podlove_data = r.json()
        assert "link" in podlove_data
        assert podlove_data["link"] == episode.full_url

    def test_podlove_detail_endpoint_chaptermarks(self, api_client, episode, chaptermarks):
        """Test whether chaptermarks get delivered via podlove endpoint."""
        audio = episode.podcast_audio
        podlove_detail_url = reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk})
        r = api_client.get(podlove_detail_url, format="json")
        chapters = r.json()["chapters"]
        for chapter in chapters:
            # assert microseconds are stripped away
            assert "." not in chapter["start"]
            assert ":" in chapter["start"]
        assert len(chapters) == 3
        # assert reordering
        assert chapters[-1]["title"] == "coughing"

    def test_podlove_detail_retrieve_sets_request_when_called_directly(self, mocker):
        """A direct ``retrieve`` call (outside DRF dispatch) wires up request attributes."""

        class MockRequest:
            query_params: dict = {}

        mocker.patch("cast.api.views.authorize_audio_access")
        mocker.patch("cast.api.views.AudioPodloveDetailView.get_object")
        mocker.patch("cast.api.views.AudioPodloveDetailView.get_serializer")
        podlove_view = AudioPodloveDetailView()
        response = podlove_view.retrieve(MockRequest())
        assert response.status_code == 200

    def test_podlove_detail_malformed_episode_id_is_rejected_even_with_valid_post_anchor(self, api_client, episode):
        """Every supplied anchor must authorize: a malformed ``episode_id`` is a 404."""
        audio = episode.podcast_audio
        podlove_detail_url = reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk, "post_id": episode.pk})
        r = api_client.get(f"{podlove_detail_url}?episode_id=foo", format="json")
        assert r.status_code == 404

    def test_podlove_detail_malformed_episode_id_without_anchor_returns_404(self, api_client, episode):
        """A malformed ``episode_id`` with no other valid anchor is rejected."""
        audio = episode.podcast_audio
        podlove_detail_url = reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk})
        r = api_client.get(f"{podlove_detail_url}?episode_id=foo", format="json")
        assert r.status_code == 404

    def test_podlove_detail_episode_id_for_draft_sibling_is_rejected(self, api_client, podcast, audio, body):
        """A valid ``episode_id`` that resolves to a non-public episode of the same audio is a 404.

        Authorization must use the same anchor the serializer renders, so a draft
        episode sharing the audio cannot be surfaced as the episode link.
        """
        from cast.devdata import create_episode

        live_episode = create_episode(blog=podcast, podcast_audio=audio, num=10, body=body)
        draft_episode = create_episode(blog=podcast, podcast_audio=audio, num=11, body=body)
        draft_episode.live = False
        draft_episode.save(update_fields=["live"])

        podlove_detail_url = reverse(
            "cast:api:audio_podlove_detail", kwargs={"pk": audio.pk, "post_id": live_episode.pk}
        )
        r = api_client.get(f"{podlove_detail_url}?episode_id={draft_episode.pk}", format="json")
        assert r.status_code == 404

    def test_podlove_podlove_detail_endpoint_show_metadata_without_artwork(self, api_client, episode):
        """Test whether the podlove detail endpoint includes show metadata, but no artwork."""
        audio = episode.podcast_audio
        podlove_detail_url = reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk, "post_id": episode.pk})

        r = api_client.get(podlove_detail_url, format="json")
        assert r.status_code == 200

        podlove_data = r.json()
        podcast = episode.blog.specific
        assert "show" in podlove_data
        assert podlove_data["show"]["title"] == podcast.title
        assert podlove_data["show"]["subtitle"] == podcast.subtitle
        assert podlove_data["show"]["poster"] == ""
        assert podlove_data["show"]["link"] == podcast.full_url

    def test_podlove_podlove_detail_endpoint_show_metadata_with_cover_image(self, image, episode, mocker):
        mock_rendition = mocker.MagicMock(url="/media/podlove.jpg")
        mocker.patch.object(image, "get_rendition", return_value=mock_rendition)
        serializer = AudioPodloveSerializer(context={"post": episode})
        episode.cover_image = image
        metadata = serializer.get_show(episode.podcast_audio)
        assert metadata["poster"] == mock_rendition.url

    def test_podlove_podlove_detail_endpoint_show_metadata(
        self, api_client, image, episode_with_podcast_with_cover_image, mocker
    ):
        """Test whether the podlove detail endpoint includes show metadata."""
        mock_rendition = mocker.MagicMock(url="/media/podlove.jpg")
        mocker.patch("wagtail.images.models.Image.get_rendition", return_value=mock_rendition)
        episode = episode_with_podcast_with_cover_image
        audio = episode.podcast_audio
        podcast = episode.blog.specific

        podlove_detail_url = reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk, "post_id": episode.pk})
        r = api_client.get(podlove_detail_url, format="json")
        assert r.status_code == 200

        podlove_data = r.json()
        assert "show" in podlove_data
        assert podlove_data["show"]["title"] == podcast.title
        assert podlove_data["show"]["subtitle"] == podcast.subtitle
        assert podlove_data["show"]["poster"] == "http://testserver" + mock_rendition.url
        assert podlove_data["show"]["link"] == podcast.full_url

    def test_podlove_player_config(self, api_client):
        """Test whether the podlove player config endpoint returns the player config."""
        url = reverse("cast:api:player_config")
        response = api_client.get(url, format="json")
        assert response.status_code == 200
        config = response.json()
        assert "activeTab" in config

    def test_podlove_player_config_bootstrap5_light(self, api_client, mocker):
        url = reverse("cast:api:player_config")
        mocker.patch("cast.api.views.get_template_base_dir", return_value="bootstrap5")
        response = api_client.get(url, format="json")
        assert response.status_code == 200
        config = response.json()
        tokens = config["theme"]["tokens"]
        assert tokens["brand"] == "#d97706"
        assert tokens["alt"] == "#ffffff"
        fonts = config["theme"]["fonts"]
        assert fonts["regular"]["family"][0] == "Inter"

    def test_podlove_player_config_bootstrap5_dark_override(self, api_client, mocker, settings):
        url = reverse("cast:api:player_config")
        mocker.patch("cast.api.views.get_template_base_dir", return_value="bootstrap5")
        settings.CAST_PODLOVE_PLAYER_THEMES = {
            "bootstrap5": {
                "dark": {
                    "tokens": {
                        "brand": "#111111",
                    }
                }
            }
        }
        response = api_client.get(f"{url}?color_scheme=dark", format="json")
        assert response.status_code == 200
        config = response.json()
        tokens = config["theme"]["tokens"]
        assert tokens["brand"] == "#111111"

    def test_podlove_player_config_bootstrap5_fonts_override(self, api_client, mocker, settings):
        url = reverse("cast:api:player_config")
        mocker.patch("cast.api.views.get_template_base_dir", return_value="bootstrap5")
        settings.CAST_PODLOVE_PLAYER_THEMES = {
            "bootstrap5": {
                "light": {
                    "fonts": {
                        "regular": {
                            "family": ["CustomSans"],
                        }
                    }
                }
            }
        }
        response = api_client.get(url, format="json")
        assert response.status_code == 200
        config = response.json()
        fonts = config["theme"]["fonts"]
        assert fonts["regular"]["family"][0] == "CustomSans"

    def test_podlove_player_config_default_override(self, api_client, mocker, settings):
        url = reverse("cast:api:player_config")
        mocker.patch("cast.api.views.get_template_base_dir", return_value="plain")
        settings.CAST_PODLOVE_PLAYER_THEMES = {
            "default": {
                "tokens": {
                    "brand": "#123456",
                }
            }
        }
        response = api_client.get(url, format="json")
        assert response.status_code == 200
        config = response.json()
        tokens = config["theme"]["tokens"]
        assert tokens["brand"] == "#123456"

    def test_podlove_player_config_bootstrap5_non_scheme_override(self, api_client, mocker, settings):
        url = reverse("cast:api:player_config")
        mocker.patch("cast.api.views.get_template_base_dir", return_value="bootstrap5")
        settings.CAST_PODLOVE_PLAYER_THEMES = {
            "bootstrap5": {
                "tokens": {
                    "brand": "#abcdef",
                }
            }
        }
        response = api_client.get(f"{url}?color_scheme=dark", format="json")
        assert response.status_code == 200
        config = response.json()
        tokens = config["theme"]["tokens"]
        assert tokens["brand"] == "#abcdef"

    def test_audio_podlove_serializer_get_transcripts(self, mocker):
        """Test whether the audio podlove serializer returns the correct transcripts."""
        # Given an episode without transcripts
        episode = mocker.MagicMock()
        episode.podcast_audio = None
        serializer = AudioPodloveSerializer(context={"post": episode})
        # When we call the get_transcripts method, then we expect an empty list
        assert serializer.get_transcripts(episode.podcast_audio) == []

        # Given an episode with an audio with a transcript without a podlove file
        # When we call the get_transcripts method, then we expect an empty list
        audio = mocker.MagicMock()
        audio.transcript = mocker.MagicMock()
        audio.transcript.podlove = None
        assert serializer.get_transcripts(audio) == []

        # Given an episode with an audio with a transcript with a podlove file containing valid JSON
        mock_file = mocker.MagicMock()
        mock_file.__enter__.return_value = mock_file
        mock_file.read.return_value = json.dumps({"transcripts": [{"text": "Hello"}]})

        mock_podlove = mocker.MagicMock()
        mock_podlove.open.return_value = mock_file

        transcript = mocker.MagicMock()
        transcript.podlove = mock_podlove

        audio = mocker.MagicMock()
        audio.transcript = transcript

        # When we call the get_transcripts method, then we expect the transcripts to be returned
        result = serializer.get_transcripts(audio)
        assert result == [{"text": "Hello"}]

        # Given an invalid key for the transcripts
        mock_file.read.return_value = json.dumps({"invalid_key": [{"text": "Hello"}]})

        # When we call the get_transcripts method, then we expect an empty list
        assert serializer.get_transcripts(audio) == []

        # Given invalid JSON in the podlove file
        mock_file.read.return_value = "{ invalid json }"

        # When we call the get_transcripts method, then we expect an empty list
        assert serializer.get_transcripts(audio) == []

    def test_audio_podlove_serializer_get_contributors(self, mocker):
        """get_contributors gracefully handles missing transcripts, files, and invalid JSON."""
        # Given an episode without an audio/transcript
        episode = mocker.MagicMock()
        episode.podcast_audio = None
        serializer = AudioPodloveSerializer(context={"post": episode})
        # When we call get_contributors, then we expect an empty list
        assert serializer.get_contributors(episode.podcast_audio) == []

        # Given an audio with a transcript without a podlove file
        audio = mocker.MagicMock()
        audio.transcript = mocker.MagicMock()
        audio.transcript.podlove = None
        assert serializer.get_contributors(audio) == []

        # Given a podlove file with valid diarized JSON
        mock_file = mocker.MagicMock()
        mock_file.__enter__.return_value = mock_file
        mock_file.read.return_value = json.dumps(
            {"transcripts": [{"speaker": "Alice", "voice": "Alice", "text": "Hello"}]}
        )
        mock_podlove = mocker.MagicMock()
        mock_podlove.open.return_value = mock_file
        transcript = mocker.MagicMock()
        transcript.podlove = mock_podlove
        audio = mocker.MagicMock()
        audio.transcript = transcript
        # When we call get_contributors, then we expect one contributor per label
        assert serializer.get_contributors(audio) == [{"id": "Alice", "name": "Alice"}]

        # Given a podlove file without a "transcripts" key
        mock_file.read.return_value = json.dumps({"invalid_key": []})
        assert serializer.get_contributors(audio) == []

        # Given invalid JSON in the podlove file
        mock_file.read.return_value = "{ invalid json }"
        assert serializer.get_contributors(audio) == []

        # Given podlove JSON that is not an object
        mock_file.read.return_value = json.dumps([])
        assert serializer.get_contributors(audio) == []

        # Given a podlove file that is missing from storage
        mock_podlove.open.side_effect = FileNotFoundError
        assert serializer.get_contributors(audio) == []

    def test_podlove_detail_endpoint_includes_contributors(self, api_client, episode):
        """Diarized transcript speaker labels surface as top-level Podlove player contributors."""
        audio = episode.podcast_audio
        dominik = Contributor.objects.create(display_name="Dominik", slug="dominik")
        jochen = Contributor.objects.create(display_name="Jochen", slug="jochen")
        EpisodeContributor.objects.create(
            episode=episode,
            contributor=dominik,
            role=EpisodeContributor.ROLE_HOST,
            sort_order=0,
        )
        EpisodeContributor.objects.create(
            episode=episode,
            contributor=jochen,
            role=EpisodeContributor.ROLE_GUEST,
            sort_order=1,
        )
        create_transcript(
            audio=audio,
            podlove={
                "transcripts": [
                    {
                        "start": "00:00:00.000",
                        "end": "00:00:01.000",
                        "speaker": "Dominik",
                        "voice": "Dominik",
                        "text": "Hallo",
                    },
                    {
                        "start": "00:00:01.000",
                        "end": "00:00:02.000",
                        "speaker": "Jochen",
                        "voice": "Jochen",
                        "text": "Hi",
                    },
                    {
                        "start": "00:00:02.000",
                        "end": "00:00:03.000",
                        "speaker": "Dominik",
                        "voice": "Dominik",
                        "text": "Tschüss",
                    },
                ]
            },
        )
        podlove_detail_url = reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk})

        r = api_client.get(podlove_detail_url, format="json")
        assert r.status_code == 200

        data = r.json()
        # contributors are deduplicated in first-appearance order
        assert data["contributors"] == [
            {"id": "Dominik", "name": "Dominik"},
            {"id": "Jochen", "name": "Jochen"},
        ]
        # the existing transcripts payload stays behavior-compatible
        assert [segment["text"] for segment in data["transcripts"]] == ["Hallo", "Hi", "Tschüss"]

    def test_podlove_detail_endpoint_sanitizes_draft_and_unmapped_speakers(self, api_client, episode):
        """Public player output only exposes speaker labels from live episode contributors."""
        audio = episode.podcast_audio
        live_contributor = Contributor.objects.create(display_name="Live Host", slug="live-host")
        EpisodeContributor.objects.create(
            episode=episode,
            contributor=live_contributor,
            role=EpisodeContributor.ROLE_HOST,
            sort_order=0,
        )
        draft_contributor = Contributor.objects.create(display_name="Draft Guest", slug="draft-guest")
        episode.contributor_assignments.add(
            EpisodeContributor(
                contributor=draft_contributor,
                role=EpisodeContributor.ROLE_GUEST,
                sort_order=1,
            )
        )
        episode.save_revision()
        transcript = create_transcript(
            audio=audio,
            podlove={
                "transcripts": [
                    {"speaker": "Live Host", "voice": "Live Host", "text": "Live speaker"},
                    {"speaker": "Draft Guest", "voice": "Draft Guest", "text": "Draft speaker"},
                    {"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Unmapped speaker"},
                ]
            },
        )
        podlove_detail_url = reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk, "post_id": episode.pk})

        response = api_client.get(podlove_detail_url, format="json")

        assert response.status_code == 200
        data = response.json()
        assert data["contributors"] == [{"id": "Live Host", "name": "Live Host"}]
        assert data["transcripts"][0]["speaker"] == "Live Host"
        assert "speaker" not in data["transcripts"][1]
        assert "voice" not in data["transcripts"][1]
        assert "speaker" not in data["transcripts"][2]
        assert "voice" not in data["transcripts"][2]
        with transcript.podlove.open("r") as podlove_file:
            stored_data = json.load(podlove_file)
        assert stored_data["transcripts"][1]["speaker"] == "Draft Guest"
        assert stored_data["transcripts"][2]["speaker"] == "Speaker 1"

    def test_podlove_detail_endpoint_applies_mapping_after_s3_style_prior_read(
        self, api_client, episode, s3_style_fieldfile_reopen_guard
    ):
        audio = episode.podcast_audio
        contributor = Contributor.objects.create(display_name="Alice", slug="api-s3-alice")
        EpisodeContributor.objects.create(
            episode=episode,
            contributor=contributor,
            role=EpisodeContributor.ROLE_HOST,
            sort_order=0,
        )
        transcript = create_transcript(
            audio=audio,
            podlove={"transcripts": [{"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Mapped speaker"}]},
        )
        fingerprint = transcript.transcript_artifact_fingerprint()
        mapping = transcript.speaker_mappings.get(speaker_label="Speaker 1")
        mapping.contributor = contributor
        mapping.review_state = TranscriptSpeakerMapping.ReviewState.APPROVED
        mapping.source_artifact_fingerprint = fingerprint
        mapping.save()
        s3_style_fieldfile_reopen_guard()
        podlove_detail_url = reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk, "post_id": episode.pk})

        response = api_client.get(podlove_detail_url, format="json")

        assert response.status_code == 200
        data = response.json()
        assert data["contributors"] == [{"id": "Alice", "name": "Alice"}]
        assert data["transcripts"][0]["speaker"] == "Alice"
        assert data["transcripts"][0]["voice"] == "Alice"

    def test_podlove_detail_endpoint_disabled_audio_suppresses_speakers(self, api_client, episode):
        """Audio-level disabled mode hides otherwise public transcript speaker labels."""
        audio = episode.podcast_audio
        audio.transcript_diarization_mode = Audio.TranscriptDiarizationMode.DISABLED
        audio.save(update_fields=["transcript_diarization_mode"], duration=False, cache_file_sizes=False)
        live_contributor = Contributor.objects.create(display_name="Live Host", slug="disabled-api-live-host")
        EpisodeContributor.objects.create(
            episode=episode,
            contributor=live_contributor,
            role=EpisodeContributor.ROLE_HOST,
            sort_order=0,
        )
        transcript = create_transcript(
            audio=audio,
            podlove={
                "transcripts": [
                    {"speaker": "Live Host", "voice": "Live Host", "text": "Live speaker"},
                    {"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Generic speaker"},
                ]
            },
        )
        podlove_detail_url = reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk, "post_id": episode.pk})

        response = api_client.get(podlove_detail_url, format="json")

        assert response.status_code == 200
        data = response.json()
        assert data["contributors"] == []
        assert "speaker" not in data["transcripts"][0]
        assert "voice" not in data["transcripts"][0]
        assert "speaker" not in data["transcripts"][1]
        assert "voice" not in data["transcripts"][1]
        with transcript.podlove.open("r") as podlove_file:
            stored_data = json.load(podlove_file)
        assert stored_data["transcripts"][0]["speaker"] == "Live Host"
        assert stored_data["transcripts"][1]["speaker"] == "Speaker 1"

    def test_podlove_detail_endpoint_rejects_draft_only_audio(self, api_client, episode):
        """The podlove config is not served when the audio has no live episode anchor."""
        episode.live = False
        episode.save(update_fields=["live"])
        audio = episode.podcast_audio
        create_transcript(
            audio=audio,
            podlove={
                "transcripts": [
                    {"speaker": "Draft Guest", "voice": "Draft Guest", "text": "Draft speaker"},
                    {"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Unmapped speaker"},
                ]
            },
        )
        podlove_detail_url = reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk})

        response = api_client.get(podlove_detail_url, format="json")

        assert response.status_code == 404

    def test_podlove_detail_endpoint_contributors_empty_without_transcript(self, api_client, episode):
        """The contributors payload is an empty list when the audio has no transcript."""
        audio = episode.podcast_audio
        podlove_detail_url = reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk})

        r = api_client.get(podlove_detail_url, format="json")
        assert r.status_code == 200
        assert r.json()["contributors"] == []

    def test_audio_podlove_serializer_loads_podlove_once(self, api_client, episode, mocker):
        """The transcripts and contributors fields share a single Podlove JSON load per response."""
        audio = episode.podcast_audio
        create_transcript(
            audio=audio,
            podlove={"transcripts": [{"speaker": "Alice", "voice": "Alice", "text": "Hello"}]},
        )
        load_spy = mocker.spy(AudioPodloveSerializer, "_load_podlove_data")
        podlove_detail_url = reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk})

        r = api_client.get(podlove_detail_url, format="json")
        assert r.status_code == 200
        # transcripts + contributors are served from one parsed Podlove file
        assert load_spy.call_count == 1

    def test_podlove_detail_endpoint_contributor_query_count_is_constant(self, api_client):
        """Raw transcript speaker count does not affect public player query count."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from cast.devdata import create_audio, create_episode, create_podcast

        blog = create_podcast()

        def make_podlove_url(speaker_count, num):
            audio = create_audio()
            create_transcript(
                audio=audio,
                podlove={
                    "transcripts": [
                        {"speaker": f"Speaker {index}", "voice": f"Speaker {index}", "text": "x"}
                        for index in range(speaker_count)
                    ]
                },
            )
            # A live episode anchors the audio so the public endpoint serves it.
            create_episode(blog=blog, podcast_audio=audio, num=num)
            return reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk})

        url_few = make_podlove_url(1, 1)
        url_many = make_podlove_url(40, 2)

        # warm up lazy caches (content types, etc.) so the comparison is fair
        assert api_client.get(url_few, format="json").status_code == 200

        with CaptureQueriesContext(connection) as queries_few:
            response_few = api_client.get(url_few, format="json")
        with CaptureQueriesContext(connection) as queries_many:
            response_many = api_client.get(url_many, format="json")

        assert response_few.status_code == 200
        assert response_many.status_code == 200
        # The live episode has no contributors, so raw speaker labels are sanitized away.
        assert response_many.json()["contributors"] == []
        # Sanitization does not perform database work per raw transcript speaker.
        assert len(queries_many.captured_queries) == len(queries_few.captured_queries)


@pytest.mark.parametrize(
    "transcripts, expected",
    [
        # speaker-only segment
        ([{"speaker": "Alice", "text": "a"}], [{"id": "Alice", "name": "Alice"}]),
        # voice-only segment
        ([{"voice": "Bob", "text": "b"}], [{"id": "Bob", "name": "Bob"}]),
        # matching speaker and voice collapse to one contributor
        ([{"speaker": "Alice", "voice": "Alice"}], [{"id": "Alice", "name": "Alice"}]),
        # differing speaker and voice both contribute, speaker first
        (
            [{"speaker": "Alice", "voice": "Bob"}],
            [{"id": "Alice", "name": "Alice"}, {"id": "Bob", "name": "Bob"}],
        ),
        # duplicates across segments are deduplicated
        (
            [{"speaker": "Alice"}, {"speaker": "Bob"}, {"speaker": "Alice"}],
            [{"id": "Alice", "name": "Alice"}, {"id": "Bob", "name": "Bob"}],
        ),
        # blank and non-string labels are ignored
        ([{"speaker": "", "voice": "   "}, {"speaker": None, "voice": 5}], []),
        # first-appearance order is preserved (not sorted)
        (
            [{"speaker": "Zoe"}, {"speaker": "Amy"}],
            [{"id": "Zoe", "name": "Zoe"}, {"id": "Amy", "name": "Amy"}],
        ),
        # non-dict segments are skipped
        (["not a dict", 5, {"speaker": "Alice"}], [{"id": "Alice", "name": "Alice"}]),
        # an empty timeline yields no contributors
        ([], []),
        # a non-list "transcripts" value is ignored instead of raising
        (None, []),
        (1, []),
    ],
)
def test_audio_podlove_serializer_contributor_extraction(transcripts, expected):
    """Contributors are derived from non-blank speaker/voice labels in first-appearance order."""
    serializer = AudioPodloveSerializer()
    serializer._podlove_data = {"transcripts": transcripts}

    assert serializer.get_contributors(None) == expected
