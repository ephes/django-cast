from types import SimpleNamespace

import pytest
from django.core.exceptions import ObjectDoesNotExist

from cast.devdata import create_transcript
from cast.models import Contributor, EpisodeContributor
from cast.transcript_sanitization import (
    podlove_contributors_from_data,
    public_episode_from_request,
    public_speaker_labels_for_audio,
    public_speaker_labels_for_episode,
    public_speaker_labels_for_transcript,
    sanitize_dote_data,
    sanitize_podlove_data,
    sanitize_webvtt_content,
    strict_public_speaker_labels_for_audio,
    strict_public_speaker_labels_for_transcript,
)


@pytest.mark.django_db
def test_public_speaker_labels_for_episode_edge_cases(episode, audio):
    contributor = Contributor.objects.create(display_name="Live Host", slug="live-host")
    EpisodeContributor.objects.create(episode=episode, contributor=contributor, role=EpisodeContributor.ROLE_HOST)

    assert public_speaker_labels_for_episode(None) is None
    assert public_speaker_labels_for_episode(SimpleNamespace()) is None
    assert public_speaker_labels_for_episode(episode, audio=audio) == {"Live Host"}
    assert public_speaker_labels_for_episode(episode, audio=SimpleNamespace(pk=-1)) == set()

    episode.live = False
    assert public_speaker_labels_for_episode(episode, audio=audio) == set()


def test_public_speaker_labels_for_transcript_without_episode_context():
    assert public_speaker_labels_for_transcript(SimpleNamespace(audio=SimpleNamespace())) is None
    assert strict_public_speaker_labels_for_transcript(SimpleNamespace(audio=SimpleNamespace())) == set()


def test_public_speaker_labels_for_transcript_ignores_broken_episode_managers():
    class BrokenEpisodes:
        def filter(self, **_kwargs):
            raise TypeError("broken")

    transcript = SimpleNamespace(audio=SimpleNamespace(episodes=BrokenEpisodes()))

    assert public_speaker_labels_for_transcript(transcript) is None


def test_public_speaker_labels_for_audio_without_transcript():
    assert public_speaker_labels_for_audio(SimpleNamespace()) is None
    assert strict_public_speaker_labels_for_audio(SimpleNamespace()) == set()


def test_public_speaker_labels_for_audio_with_missing_related_transcript():
    class AudioWithoutTranscript:
        @property
        def transcript(self):
            raise ObjectDoesNotExist

    assert public_speaker_labels_for_audio(AudioWithoutTranscript()) is None


@pytest.mark.django_db
def test_public_episode_from_request(rf, episode):
    transcript = create_transcript(audio=episode.podcast_audio, podlove={"transcripts": []})

    assert public_episode_from_request(rf.get("/"), transcript=transcript) is None
    assert public_episode_from_request(rf.get("/", {"episode_id": "not-an-int"}), transcript=transcript) is None
    assert public_episode_from_request(rf.get("/", {"episode_id": episode.pk}), transcript=transcript) == episode


def test_sanitize_podlove_data_edge_cases():
    data = {"transcripts": [{"speaker": "Alice", "voice": "Alice"}, "not-a-segment"]}

    assert sanitize_podlove_data(data, None) is data
    assert sanitize_podlove_data({"transcripts": "not-a-list"}, {"Alice"}) == {"transcripts": "not-a-list"}
    assert sanitize_podlove_data(data, {"Alice"}) == data
    assert sanitize_podlove_data(data, set()) == {"transcripts": [{}, "not-a-segment"]}


def test_sanitize_dote_data_edge_cases():
    data = {"lines": [{"speakerDesignation": "Alice"}, "not-a-line"]}

    assert sanitize_dote_data(data, None) is data
    assert sanitize_dote_data({"lines": "not-a-list"}, {"Alice"}) == {"lines": "not-a-list"}
    assert sanitize_dote_data(data, {"Alice"}) == data
    assert sanitize_dote_data(data, set()) == {"lines": [{"speakerDesignation": ""}, "not-a-line"]}


def test_podlove_contributors_from_data_edge_cases():
    assert podlove_contributors_from_data({"transcripts": "not-a-list"}) == []
    assert podlove_contributors_from_data({"transcripts": ["not-a-segment", {"speaker": "Alice"}]}) == [
        {"id": "Alice", "name": "Alice"}
    ]


def test_sanitize_webvtt_content_edge_cases():
    assert sanitize_webvtt_content("WEBVTT\n", None) == "WEBVTT\n"

    content = (
        "WEBVTT\r\n\r\n"
        "00:00:00.000 --> 00:00:01.000\r\n"
        "<v Live Host>Allowed voice</v>\r\n\r\n"
        "00:00:01.000 --> 00:00:02.000\n"
        "Speaker 1: Allowed generic prefix\n\n"
        "00:00:02.000 --> 00:00:03.000\n"
        "Speaker 2: Stripped generic prefix\n\n"
        "00:00:03.000 --> 00:00:04.000\n"
        "<v Speaker 3>Stripped voice span</v>\n\n"
        "00:00:04.000 --> 00:00:05.000\n"
        "<v Live Host>Allowed voice</v> <v Speaker 4>Disallowed voice</v>\n\n"
        "00:00:05.000 --> 00:00:06.000\n"
        "<v Speaker 5>Opening-only voice tag"
    )

    sanitized = sanitize_webvtt_content(content, {"Live Host", "Speaker 1"})

    assert "<v Live Host>Allowed voice</v>" in sanitized
    assert "Speaker 1: Allowed generic prefix" in sanitized
    assert "Speaker 2" not in sanitized
    assert "Stripped generic prefix" in sanitized
    assert "Speaker 3" not in sanitized
    assert "Stripped voice span" in sanitized
    assert "<v Live Host>Allowed voice</v> Disallowed voice" in sanitized
    assert "Speaker 4" not in sanitized
    assert "Speaker 5" not in sanitized
    assert "Opening-only voice tag" in sanitized
