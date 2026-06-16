import json
from datetime import datetime, timedelta
from urllib.parse import urlencode

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.request import Request

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

from .factories import PostFactory, UserFactory

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


class TestCommentTrainingData:
    pytestmark = pytest.mark.django_db

    @classmethod
    def setup_class(cls):
        cls.url = reverse("cast:api:comment-training-data")

    def test_get_comment_training_data_without_authentication(self, api_client):
        """Should not be accessible without authentication."""
        r = api_client.get(self.url, format="json")
        assert r.status_code == 403

    def test_get_comment_training_data_with_non_staff_authentication(self, api_client):
        """Authenticated non-staff users must not access comment training data."""
        user = UserFactory()
        api_client.login(username=user.username, password="password")
        r = api_client.get(self.url, format="json")
        assert r.status_code == 403

    def test_get_comment_training_data_with_staff_authentication(self, api_client):
        """Staff users may access comment training data."""
        from django_comments import get_model as get_comments_model

        get_comments_model().objects.all().delete()
        user = UserFactory(is_staff=True)
        api_client.login(username=user.username, password="password")
        r = api_client.get(self.url, format="json")
        assert r.status_code == 200
        assert r.json() == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    "date, post_filter, len_result",
    [
        (datetime(2022, 8, 22), "true", 0),  # wrong date facet -> not found
        (timezone.now(), "true", 1),  # correct date facet -> found
        (datetime(2022, 8, 22), "false", 1),  # wrong date facet and no post filter -> found
    ],
)
def test_wagtail_pages_api_with_post_filter(date, post_filter, len_result, rf, blog, post):
    viewset = FilteredPagesAPIViewSet()
    path = blog.wagtail_api_pages_url
    date_facet = f"{date.year}-{date.month}"
    request = rf.get(
        f"{path}?child_of={blog.pk}&type=cast.Post&date_facets={date_facet}&use_post_filter={post_filter}"
    )
    viewset.request = request
    queryset = viewset.get_queryset()
    assert len(queryset) == len_result


@pytest.mark.django_db
def test_wagtail_pages_api_with_post_filter_and_fulltext_search(rf, blog, post):
    viewset = FilteredPagesAPIViewSet()
    path = blog.wagtail_api_pages_url
    search_param = "search=foo"
    request = rf.get(f"{path}?child_of={blog.pk}&type=cast.Post&{search_param}&use_post_filter=true")
    viewset.request = request
    queryset = viewset.get_queryset()
    assert len(queryset) == 0


@pytest.mark.django_db
def test_wagtail_pages_api_template_base_dir_override(rf, blog, post):
    viewset = FilteredPagesAPIViewSet()
    path = blog.wagtail_api_pages_url
    request = rf.get(f"{path}?child_of={blog.pk}&type=cast.Post&template_base_dir=plain")
    viewset.request = request
    viewset.get_queryset()
    assert request.cast_template_base_dir == "plain"


@pytest.mark.django_db
def test_wagtail_pages_api_theme_alias_override(rf, blog, post):
    viewset = FilteredPagesAPIViewSet()
    path = blog.wagtail_api_pages_url
    request = rf.get(f"{path}?child_of={blog.pk}&type=cast.Post&theme=plain")
    viewset.request = request
    viewset.get_queryset()
    assert request.cast_template_base_dir == "plain"


def test_wagtail_pages_api_template_base_dir_invalid_choice(rf):
    viewset = FilteredPagesAPIViewSet()
    request = rf.get("/?template_base_dir=missing-theme")
    viewset.request = request
    viewset._apply_template_base_dir_override()
    assert not hasattr(request, "cast_template_base_dir")


def test_wagtail_pages_api_template_base_dir_sets_wrapped_request(rf):
    viewset = FilteredPagesAPIViewSet()
    request = Request(rf.get("/?template_base_dir=plain"))
    viewset.request = request
    viewset._apply_template_base_dir_override()
    assert request.cast_template_base_dir == "plain"
    assert request._request.cast_template_base_dir == "plain"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field_name, api_viewset_class",
    [
        ("slug", FilteredPagesAPIViewSet),
        ("title", CastImagesAPIViewSet),
    ],
)
def test_wagtail_api_viewsets_filter_null_bytes(rf, field_name, api_viewset_class):
    # Given a request filtering for a slug containing a null byte
    input_with_null_byte = "1%00%EF%BF%BD%EF%BF%BD%EF%BF%BD%EF%BF%BD%252527%252522"
    request = rf.get(f"?{field_name}={input_with_null_byte}&harmless=foo")
    viewset = api_viewset_class()
    viewset.request = request
    queryset = viewset.get_queryset()
    # When the queryset is filtered
    queryset = viewset.filter_queryset(queryset)
    # Then there should be no null bytes in the resulting SQL query params
    _sql, params = queryset.query.sql_with_params()
    assert all(["\x00" not in str(param) for param in params])


@pytest.mark.django_db
def test_facet_counts_list(api_client, blog):
    """
    Test whether the facet counts list endpoint returns a list of all blogs
    and the blog is included in the result.
    """
    url = reverse("cast:api:facet-counts-list")
    r = api_client.get(url, format="json")
    assert r.status_code == 200

    [result] = r.json()["results"]
    assert "id" in result
    assert "url" in result
    assert result["id"] == blog.pk


def test_facet_counts_list_post(api_client):
    """
    Someone sent a lot of post data to the facet counts list endpoint.
    Make sure she gets a proper 405 instead of a 500 next time.
    """
    url = reverse("cast:api:facet-counts-list")
    r = api_client.post(url, data={})
    assert r.status_code == 405


@pytest.mark.django_db
def test_facet_counts_detail(api_client, blog, post):
    """
    Test whether the facet counts detail endpoint returns the
    facet counts for a specific blog.
    """
    # Given a post with a category and a tag
    category = PostCategory.objects.create(name="category", slug="category")
    post.categories.add(category)
    post.tags.add("tag")
    post.save()

    # When we request the facet counts for the blog
    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})
    r = api_client.get(url, format="json")
    assert r.status_code == 200

    result = r.json()
    facet_counts = result["facet_counts"]

    # Then we expect the correct facet counts to be returned
    assert facet_counts["date_facets"][0]["slug"] == post.visible_date.strftime("%Y-%m")
    assert facet_counts["date_facets"][0]["name"] == post.visible_date.strftime("%Y-%m")
    assert facet_counts["date_facets"][0]["count"] == 1

    assert facet_counts["category_facets"][0]["slug"] == category.slug
    assert facet_counts["category_facets"][0]["count"] == 1

    assert facet_counts["tag_facets"][0]["slug"] == "tag"
    assert facet_counts["tag_facets"][0]["count"] == 1

    # make sure adding a search param filters the results
    r = api_client.get(f"{url}?search=foobar", format="json")
    assert r.status_code == 200

    result = r.json()
    date_facets = result["facet_counts"]["date_facets"]
    assert len(date_facets) == 0


@pytest.mark.django_db
def test_facet_counts_detail_unpublished_blog_returns_404(api_client, blog):
    blog.unpublish()
    blog.refresh_from_db()

    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})
    r = api_client.get(url, format="json")

    assert r.status_code == 404


@pytest.mark.django_db
def test_facet_counts_detail_live_blog_still_returns_200(api_client, blog):
    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})
    r = api_client.get(url, format="json")

    assert r.status_code == 200
    assert r.json()["id"] == blog.pk


def _create_modal_facet_posts(blog, body):
    til = PostCategory.objects.create(name="Today I Learned", slug="til")
    weeknotes = PostCategory.objects.create(name="WeekNotes", slug="weeknotes")

    jan_python = PostFactory(
        owner=blog.owner,
        parent=blog,
        title="Python January",
        slug="python-january",
        body=body,
        visible_date=timezone.make_aware(datetime(2026, 1, 10)),
    )
    jan_python.tags.add("python")
    jan_python.categories.add(til)
    jan_python.save()

    feb_django = PostFactory(
        owner=blog.owner,
        parent=blog,
        title="Django February",
        slug="django-february",
        body=body,
        visible_date=timezone.make_aware(datetime(2026, 2, 12)),
    )
    feb_django.tags.add("django")
    feb_django.categories.add(til)
    feb_django.save()

    feb_python = PostFactory(
        owner=blog.owner,
        parent=blog,
        title="Python Weeknotes",
        slug="python-weeknotes",
        body=body,
        visible_date=timezone.make_aware(datetime(2026, 2, 20)),
    )
    feb_python.tags.add("python")
    feb_python.categories.add(weeknotes)
    feb_python.save()


@pytest.mark.django_db
def test_facet_counts_detail_mode_modal_schema(api_client, blog, post):
    category = PostCategory.objects.create(name="category", slug="category")
    post.categories.add(category)
    post.tags.add("tag")
    post.save()

    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})
    r = api_client.get(f"{url}?mode=modal", format="json")
    assert r.status_code == 200

    result = r.json()
    assert result["mode"] == "modal"
    assert isinstance(result["result_count"], int)
    assert set(result["groups"].keys()) == {"date_facets", "category_facets", "tag_facets"}

    for group in result["groups"].values():
        assert set(group.keys()) == {"selected", "all_count", "options"}
        assert isinstance(group["selected"], str)
        assert isinstance(group["all_count"], int)
        assert isinstance(group["options"], list)
        for option in group["options"]:
            assert set(option.keys()) == {"slug", "name", "count"}


@pytest.mark.django_db
def test_facet_counts_detail_mode_modal_malformed_search_does_not_raise(api_client, blog, post):
    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})
    query_string = urlencode({"mode": "modal", "search": SCANNER_SEARCH_PAYLOAD})

    r = api_client.get(f"{url}?{query_string}", format="json")

    assert r.status_code == 200
    assert r.json()["mode"] == "modal"


@pytest.mark.django_db
def test_facet_counts_detail_unknown_mode_returns_legacy_response(api_client, blog, post):
    post.tags.add("tag")
    post.save()
    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})

    legacy = api_client.get(url, format="json")
    unknown_mode = api_client.get(f"{url}?mode=unknown", format="json")

    assert legacy.status_code == 200
    assert unknown_mode.status_code == 200
    assert unknown_mode.json() == legacy.json()


@pytest.mark.django_db
def test_facet_counts_detail_mode_modal_universe_merge_includes_zero_count_options(api_client, blog, body):
    _create_modal_facet_posts(blog, body)
    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})

    r = api_client.get(f"{url}?mode=modal&tag_facets=django&category_facets=weeknotes", format="json")
    assert r.status_code == 200
    result = r.json()

    assert result["result_count"] == 0
    date_counts = {option["slug"]: option["count"] for option in result["groups"]["date_facets"]["options"]}
    assert date_counts["2026-01"] == 0
    assert date_counts["2026-02"] == 0

    tag_counts = {option["slug"]: option["count"] for option in result["groups"]["tag_facets"]["options"]}
    assert tag_counts["django"] == 0
    assert tag_counts["python"] == 1


@pytest.mark.django_db
def test_facet_counts_detail_mode_modal_uses_own_group_exclusion(api_client, blog, body):
    _create_modal_facet_posts(blog, body)
    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})

    r = api_client.get(f"{url}?mode=modal&tag_facets=python&category_facets=til", format="json")
    assert r.status_code == 200
    result = r.json()

    assert result["result_count"] == 1
    assert result["groups"]["tag_facets"]["all_count"] == 2
    tag_counts = {option["slug"]: option["count"] for option in result["groups"]["tag_facets"]["options"]}
    assert tag_counts["python"] == 1
    assert tag_counts["django"] == 1


@pytest.mark.django_db
def test_facet_counts_detail_mode_modal_omits_groups_not_configured(api_client, blog, post, mocker):
    post.tags.add("tag")
    post.save()
    mocker.patch("cast.modal_facet_counts.appsettings.CAST_FILTERSET_FACETS", ["search", "tag_facets", "o"])

    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})
    r = api_client.get(f"{url}?mode=modal", format="json")
    assert r.status_code == 200
    assert set(r.json()["groups"].keys()) == {"tag_facets"}


@pytest.mark.django_db
def test_facet_counts_detail_mode_modal_empty_blog(api_client, blog):
    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})
    r = api_client.get(f"{url}?mode=modal", format="json")
    assert r.status_code == 200

    result = r.json()
    assert result["result_count"] == 0
    assert set(result["groups"].keys()) == {"date_facets", "category_facets", "tag_facets"}
    for group in result["groups"].values():
        assert group["all_count"] == 0
        assert group["selected"] == ""
        assert group["options"] == []


@pytest.mark.django_db
def test_facet_counts_detail_mode_modal_search_aggregation_path(api_client, blog, post, mocker):
    post.tags.add("python")
    post.save()
    mocker.patch("cast.modal_facet_counts._supports_aggregation_on_queryset", return_value=True)
    fallback_spy = mocker.spy(modal_facet_counts, "_queryset_from_pk_fallback")

    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})
    r = api_client.get(f"{url}?mode=modal&search={post.title}", format="json")
    assert r.status_code == 200
    assert fallback_spy.call_count == 0
    assert r.json()["mode"] == "modal"


@pytest.mark.django_db
def test_facet_counts_detail_mode_modal_search_aggregation_fallback_path(api_client, blog, post, mocker):
    post.tags.add("python")
    post.save()
    mocker.patch("cast.modal_facet_counts._supports_aggregation_on_queryset", return_value=False)
    fallback_spy = mocker.spy(modal_facet_counts, "_queryset_from_pk_fallback")

    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})
    r = api_client.get(f"{url}?mode=modal&search={post.title}", format="json")
    assert r.status_code == 200
    assert fallback_spy.call_count > 0
    assert r.json()["mode"] == "modal"


@pytest.mark.django_db
def test_facet_counts_detail_mode_modal_aggregation_probe_runs_once(api_client, blog, post, mocker):
    post.tags.add("python")
    post.save()
    probe_spy = mocker.spy(modal_facet_counts, "_supports_aggregation_on_queryset")

    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})
    r = api_client.get(f"{url}?mode=modal", format="json")
    assert r.status_code == 200
    assert probe_spy.call_count == 1


@pytest.mark.django_db
def test_facet_counts_detail_mode_modal_with_date_facets(api_client, blog, body):
    """Selecting a date_facets param filters posts to the matching month."""
    _create_modal_facet_posts(blog, body)
    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})

    r = api_client.get(f"{url}?mode=modal&date_facets=2026-01", format="json")
    assert r.status_code == 200
    result = r.json()
    assert result["result_count"] == 1
    assert result["groups"]["date_facets"]["selected"] == "2026-01"


@pytest.mark.django_db
@pytest.mark.parametrize("date_value", ["not-a-date", "2026-13", "abc"])
def test_facet_counts_detail_mode_modal_with_invalid_date_facets(api_client, blog, body, date_value):
    """Invalid date_facets param should be normalized to empty and not filter results."""
    _create_modal_facet_posts(blog, body)
    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})

    r = api_client.get(f"{url}?mode=modal&date_facets={date_value}", format="json")
    assert r.status_code == 200
    result = r.json()
    assert result["groups"]["date_facets"]["selected"] == ""
    # Invalid facet should not filter — result_count equals all posts
    assert result["result_count"] == 3


@pytest.mark.django_db
def test_facet_counts_detail_mode_modal_with_invalid_slug_facets(api_client, blog, body):
    """Invalid slug values should be normalized to empty and not filter results."""
    _create_modal_facet_posts(blog, body)
    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})

    r = api_client.get(f"{url}?mode=modal&tag_facets=not+valid!", format="json")
    assert r.status_code == 200
    result = r.json()
    assert result["groups"]["tag_facets"]["selected"] == ""
    # Invalid facet should not filter — result_count equals all posts
    assert result["result_count"] == 3


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2026-01", "2026-01"),
        ("not-a-date", ""),
        ("2026-13", ""),
        ("", ""),
    ],
)
def test_normalize_date_facet(value, expected):
    from cast.modal_facet_counts import _normalize_date_facet

    assert _normalize_date_facet(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        ("valid-slug", "valid-slug"),
        ("invalid slug!", ""),
        ("has spaces", ""),
        ("", ""),
    ],
)
def test_normalize_slug_facet(value, expected):
    from cast.modal_facet_counts import _normalize_slug_facet

    assert _normalize_slug_facet(value) == expected


@pytest.mark.django_db
def test_supports_aggregation_on_queryset_exception(mocker):
    """When the aggregation probe raises, _supports_aggregation_on_queryset returns False."""
    from cast.modal_facet_counts import _supports_aggregation_on_queryset
    from cast.models import Post

    qs = Post.objects.none()
    original_order_by = qs.order_by

    def failing_order_by(*args, **kwargs):
        result = original_order_by(*args, **kwargs)
        mock_values = mocker.MagicMock()
        mock_values.annotate.return_value.__getitem__ = mocker.MagicMock(
            side_effect=Exception("simulated aggregation failure")
        )
        result.values = mocker.MagicMock(return_value=mock_values)
        return result

    mocker.patch.object(qs, "order_by", side_effect=failing_order_by)
    assert _supports_aggregation_on_queryset(qs) is False


@pytest.mark.django_db
def test_queryset_from_pk_fallback_empty():
    """When the input queryset is empty, _queryset_from_pk_fallback returns an empty queryset."""
    from cast.modal_facet_counts import _queryset_from_pk_fallback
    from cast.models import Post

    qs = Post.objects.none()
    result = _queryset_from_pk_fallback(qs)
    assert result.count() == 0


def test_date_rows_to_counts_skips_none_month():
    """When a row has month=None it should be silently skipped."""
    from cast.modal_facet_counts import _date_rows_to_counts

    rows = [
        (None, 3),
        (datetime(2026, 1, 1), 5),
    ]
    assert _date_rows_to_counts(rows) == {"2026-01": 5}


@pytest.mark.django_db
def test_get_comments_via_post_detail(api_client, post, comment):
    url = reverse("cast:api:wagtail:pages:detail", kwargs={"pk": post.pk})
    r = api_client.get(url, format="json")
    assert r.status_code == 200

    comments = r.json()["comments"]
    assert comments[0]["comment"] == comment.comment


@pytest.mark.django_db
def test_wagtail_api_page_detail_includes_cover_image_poster_url(api_client, post, image, mocker):
    mock_rendition = mocker.MagicMock(url="/media/podlove.jpg")
    mocker.patch("wagtail.images.models.Image.get_rendition", return_value=mock_rendition)
    post.cover_image = image
    post.save()
    url = reverse("cast:api:wagtail:pages:detail", kwargs={"pk": post.pk})
    r = api_client.get(url, format="json")
    assert r.status_code == 200

    assert r.json()["cover_image_poster_url"] == "http://testserver" + mock_rendition.url


@pytest.mark.django_db
def test_wagtail_api_page_detail_with_chooser_happy(api_client):
    """
    Access the wagtail api page detail endpoint with a post that has an image
    or video. This did throw a 500 error before -> sentry saw it -> fix it.
    """
    blog = generate_blog_with_media(media_numbers={"images": 1, "videos": 1, "galleries": 1})
    post = blog.unfiltered_published_posts.first()
    url = reverse("cast:api:wagtail:pages:detail", kwargs={"pk": post.pk})
    r = api_client.get(url, format="json")
    assert r.status_code == 200


def test_theme_list_queryset_is_none():
    view = ThemeListView()
    assert view.get_queryset() is None


@pytest.mark.django_db
def test_list_themes(api_client):
    # Given an api url to fetch the list of themes
    url = reverse("cast:api:theme-list")
    # When we request the list of themes
    r = api_client.get(url, format="json")
    assert r.status_code == 200

    # Then we expect a list of themes to be returned and include the `plain` theme
    result = r.json()
    assert "plain" in {theme["slug"] for theme in result["items"]}


@pytest.mark.django_db
def test_update_theme(api_client):
    # Given an api url to update the theme
    url = reverse("cast:api:theme-update")
    # When we post to the update theme endpoint
    r = api_client.post(url, {"theme_slug": "plain"}, format="json")
    assert r.status_code == 200

    # Then we expect a success message to be returned
    result = r.json()
    assert result["message"] == "Theme updated successfully"
    assert api_client.session.get("template_base_dir") == "plain"


@pytest.mark.django_db
def test_update_theme_invalid(api_client):
    # Given an api url to update the theme
    url = reverse("cast:api:theme-update")
    # When we post an invalid theme to the update theme endpoint
    r = api_client.post(url, {"theme_slug": "invalid"}, format="json")
    assert r.status_code == 400

    # Then we expect an error message to be returned and
    # the theme is not stored in the session
    result = r.json()
    assert result["error"] == "Theme slug is invalid"
    assert api_client.session.get("template_base_dir") is None


def test_update_theme_int_payload(api_client):
    # Given an api url to update the theme
    url = reverse("cast:api:theme-update")
    # When we post an integer payload to the update theme endpoint
    r = api_client.post(url, 23, format="json")
    assert r.status_code == 400

    # Then we expect an error message to be returned and
    # the theme is not stored in the session
    result = r.json()
    assert result["error"] == "Invalid request"


@pytest.mark.django_db
def test_render_html_with_theme_from_session(api_client, post):
    # Given we have custom theme set in the session
    r = api_client.post(
        # FIXME there's some way to update the session more elegantly
        # use this instead of the post request
        reverse("cast:api:theme-update"),
        {"theme_slug": "plain"},
        format="json",
    )
    assert r.status_code == 200

    # When we request the blog post via api
    url = reverse("cast:api:wagtail:pages:detail", kwargs={"pk": post.pk})
    r = api_client.get(url, format="json")
    assert r.status_code == 200

    # Then we expect the blog post to be rendered with the theme from the session
    assert r.context.get("template_base_dir") == "plain"
    assert all([t.name.startswith("cast/plain/") for t in r.templates])
