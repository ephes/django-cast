"""Rollout gating, the inclusion tag, and the rendered detail page for the custom player."""

import json

import pytest
from django.template.loader import render_to_string
from django.test import RequestFactory

from cast.devdata import create_transcript

from .factories import EpisodeFactory


@pytest.fixture()
def rf_request():
    return RequestFactory().get("/")


def render_audio_block(audio, page, *, render_detail, render_for_feed=False, request=None):
    return render_to_string(
        "cast/audio/audio.html",
        {
            "value": audio,
            "page": page,
            "render_detail": render_detail,
            "render_for_feed": render_for_feed,
        },
        request=request,
    )


@pytest.mark.django_db
class TestRolloutGating:
    def test_custom_detail_renders_custom_player_and_json_script(self, audio, episode, rf_request, settings):
        settings.CAST_AUDIO_PLAYER = "custom"
        create_transcript(audio=audio, podlove={"transcripts": [{"start_ms": 0, "end_ms": 1000, "text": "hi"}]})
        html = render_audio_block(audio, episode, render_detail=True, request=rf_request)
        assert f'id="cast-player-{audio.pk}"' in html
        assert f'id="cast-player-data-{audio.pk}"' in html
        assert 'type="application/json"' in html
        assert "<cast-transcript" in html
        assert "<cast-chapters" in html
        assert "podlove-player" not in html

    def test_custom_list_card_renders_no_player(self, audio, episode, rf_request, settings):
        settings.CAST_AUDIO_PLAYER = "custom"
        html = render_audio_block(audio, episode, render_detail=False, request=rf_request)
        assert "cast-audio-player" not in html
        assert "cast-player-data" not in html
        assert "podlove-player" not in html

    def test_podlove_default_unchanged(self, audio, episode, rf_request, settings):
        settings.CAST_AUDIO_PLAYER = "podlove"
        html = render_audio_block(audio, episode, render_detail=True, request=rf_request)
        assert "podlove-player" in html
        assert "cast-audio-player" not in html

    def test_feed_renders_no_web_player(self, audio, episode, rf_request, settings):
        settings.CAST_AUDIO_PLAYER = "custom"
        html = render_audio_block(audio, episode, render_detail=True, render_for_feed=True, request=rf_request)
        assert "cast-audio-player" not in html
        assert "podlove-player" not in html


@pytest.mark.django_db
class TestInclusionTagPayload:
    def test_json_script_contains_payload(self, audio, episode, rf_request, settings):
        settings.CAST_AUDIO_PLAYER = "custom"
        create_transcript(audio=audio, podlove={"transcripts": [{"start_ms": 0, "end_ms": 1000, "text": "hi"}]})
        html = render_audio_block(audio, episode, render_detail=True, request=rf_request)
        start = html.index('type="application/json"')
        snippet = html[start : html.index("</script>", start)]
        data = json.loads(snippet[snippet.index(">") + 1 :])
        assert data["audioId"] == audio.pk
        # Lazy transcript: the inline payload carries the endpoint URL, not cues.
        assert "cues" not in data["transcript"]
        assert "player-transcript" in data["transcript"]["url"]


@pytest.mark.django_db
class TestDetailPageIntegration:
    @pytest.fixture()
    def episode_with_audio_in_body(self, podcast, audio, body_with_audio):
        return EpisodeFactory(
            owner=podcast.owner,
            parent=podcast,
            title="custom player episode",
            slug="custom-player-episode",
            podcast_audio=audio,
            body=body_with_audio,
        )

    def test_custom_mode_detail_page_has_player_and_asset(self, client, episode_with_audio_in_body, audio, settings):
        settings.CAST_AUDIO_PLAYER = "custom"
        create_transcript(audio=audio, podlove={"transcripts": [{"start_ms": 0, "end_ms": 1000, "text": "hi"}]})
        response = client.get(episode_with_audio_in_body.get_url())
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert f'id="cast-player-data-{audio.pk}"' in content
        assert "cast-audio-player" in content
        assert "custom-player" in content  # the gated detail asset
        assert "podlove-player" not in content

    def test_podlove_mode_detail_page_unchanged(self, client, episode_with_audio_in_body, settings):
        settings.CAST_AUDIO_PLAYER = "podlove"
        response = client.get(episode_with_audio_in_body.get_url())
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "podlove-player" in content
        assert "cast-audio-player" not in content
