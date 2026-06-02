from types import SimpleNamespace

import pytest
from django.core.exceptions import ObjectDoesNotExist

from cast.devdata import create_transcript
from cast.models import Audio, Contributor, EpisodeContributor, TranscriptSpeakerMapping
from cast.transcript_sanitization import (
    apply_speaker_mapping_to_dote_data,
    apply_speaker_mapping_to_podlove_data,
    apply_speaker_mapping_to_webvtt_content,
    audio_transcript_diarization_disabled,
    podlove_contributors_from_data,
    public_episode_from_request,
    public_one_off_speaker_labels_for_transcript,
    public_speaker_mapping_for_transcript,
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
def test_public_speaker_mapping_context_edge_cases(episode, audio):
    class BrokenEpisodes:
        def filter(self, **_kwargs):
            raise TypeError("broken")

    class EpisodeManager:
        def filter(self, **_kwargs):
            return self

        def prefetch_related(self, *_args):
            return self

        def all(self):
            return [SimpleNamespace(visible_contributor_assignments=[SimpleNamespace(contributor_id=None)])]

    assert public_speaker_mapping_for_transcript(SimpleNamespace(audio=SimpleNamespace())) == {}
    assert public_one_off_speaker_labels_for_transcript(SimpleNamespace(audio=SimpleNamespace())) == set()
    assert (
        public_speaker_mapping_for_transcript(SimpleNamespace(audio=SimpleNamespace(episodes=BrokenEpisodes()))) == {}
    )

    fake_transcript = SimpleNamespace(audio=SimpleNamespace(episodes=EpisodeManager()))
    assert public_speaker_mapping_for_transcript(fake_transcript) == {}

    transcript = create_transcript(podlove={"transcripts": [{"speaker": "Speaker 1"}]})
    assert public_speaker_mapping_for_transcript(transcript, episode=episode) == {}

    matching_transcript = create_transcript(
        audio=episode.podcast_audio,
        podlove={"transcripts": [{"speaker": "Speaker 1"}]},
    )
    blank_mapping = matching_transcript.speaker_mappings.get(speaker_label="Speaker 1")
    blank_mapping.speaker_label = ""
    blank_mapping.display_name = "Blank Source"
    blank_mapping.review_state = TranscriptSpeakerMapping.ReviewState.APPROVED
    blank_mapping.source_artifact_fingerprint = matching_transcript.transcript_artifact_fingerprint()
    blank_mapping.save(update_fields=["speaker_label", "display_name", "review_state", "source_artifact_fingerprint"])

    assert public_speaker_mapping_for_transcript(matching_transcript, episode=episode) == {}


@pytest.mark.django_db
def test_public_speaker_mapping_uses_stable_fingerprint_after_s3_style_prior_reads(
    episode, s3_style_fieldfile_reopen_guard
):
    contributor = Contributor.objects.create(display_name="Alice", slug="s3-mapping-alice")
    EpisodeContributor.objects.create(episode=episode, contributor=contributor, role=EpisodeContributor.ROLE_HOST)
    transcript = create_transcript(
        audio=episode.podcast_audio,
        podlove={"transcripts": [{"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Podlove line"}]},
        dote={"lines": [{"speakerDesignation": "Speaker 1", "text": "DOTe line"}]},
        vtt=("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n<v Speaker 1>WebVTT line</v>\n"),
    )
    fingerprint = transcript.transcript_artifact_fingerprint()
    mapping = transcript.speaker_mappings.get(speaker_label="Speaker 1")
    mapping.contributor = contributor
    mapping.review_state = TranscriptSpeakerMapping.ReviewState.APPROVED
    mapping.source_artifact_fingerprint = fingerprint
    mapping.save()
    s3_style_fieldfile_reopen_guard()

    assert transcript.podlove_data["transcripts"][0]["speaker"] == "Speaker 1"
    assert transcript.dote_data["lines"][0]["speakerDesignation"] == "Speaker 1"
    assert "Speaker 1" in transcript._load_text_file("vtt")
    assert public_speaker_mapping_for_transcript(transcript, episode=episode) == {"Speaker 1": "Alice"}


@pytest.mark.django_db
def test_disabled_audio_returns_empty_public_speaker_labels(episode):
    contributor = Contributor.objects.create(display_name="Live Host", slug="disabled-live-host")
    EpisodeContributor.objects.create(episode=episode, contributor=contributor, role=EpisodeContributor.ROLE_HOST)
    audio = episode.podcast_audio
    audio.transcript_diarization_mode = Audio.TranscriptDiarizationMode.DISABLED
    audio.save(update_fields=["transcript_diarization_mode"], duration=False, cache_file_sizes=False)
    transcript = create_transcript(audio=audio, podlove={"transcripts": [{"speaker": "Live Host"}]})

    assert audio_transcript_diarization_disabled(audio)
    assert public_speaker_labels_for_episode(episode, audio=audio) == set()
    assert public_speaker_labels_for_audio(audio, episode=episode) == set()
    assert public_speaker_labels_for_transcript(transcript, episode=episode) == set()
    assert strict_public_speaker_labels_for_audio(audio, episode=episode) == set()
    assert strict_public_speaker_labels_for_transcript(transcript, episode=episode) == set()


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


def test_apply_speaker_mapping_to_podlove_data_edge_cases():
    assert apply_speaker_mapping_to_podlove_data({"transcripts": []}, {}) == {"transcripts": []}
    assert apply_speaker_mapping_to_podlove_data({"transcripts": "not-a-list"}, {"Speaker 1": "Alice"}) == {
        "transcripts": "not-a-list"
    }
    assert apply_speaker_mapping_to_podlove_data(
        {"transcripts": ["not-a-segment", {"speaker": "Speaker 1", "voice": "Speaker 2"}]},
        {"Speaker 1": "Alice"},
    ) == {"transcripts": ["not-a-segment", {"speaker": "Alice", "voice": "Speaker 2"}]}


def test_sanitize_dote_data_edge_cases():
    data = {"lines": [{"speakerDesignation": "Alice"}, "not-a-line"]}

    assert sanitize_dote_data(data, None) is data
    assert sanitize_dote_data({"lines": "not-a-list"}, {"Alice"}) == {"lines": "not-a-list"}
    assert sanitize_dote_data(data, {"Alice"}) == data
    assert sanitize_dote_data(data, set()) == {"lines": [{"speakerDesignation": ""}, "not-a-line"]}


def test_apply_speaker_mapping_to_dote_data_edge_cases():
    assert apply_speaker_mapping_to_dote_data({"lines": []}, {}) == {"lines": []}
    assert apply_speaker_mapping_to_dote_data({"lines": "not-a-list"}, {"Speaker 1": "Alice"}) == {
        "lines": "not-a-list"
    }
    assert apply_speaker_mapping_to_dote_data(
        {"lines": ["not-a-line", {"speakerDesignation": "Speaker 1"}]},
        {"Speaker 1": "Alice"},
    ) == {"lines": ["not-a-line", {"speakerDesignation": "Alice"}]}


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
        "<v Speaker 5>Opening-only voice tag\n\n"
        "00:00:06.000 --> 00:00:07.000\n"
        "<v.loud Live Host>Allowed classed voice</v> <v.loud Speaker 6>Disallowed classed voice</v>"
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
    assert "<v.loud Live Host>Allowed classed voice</v>" in sanitized
    assert "Speaker 6" not in sanitized
    assert "Disallowed classed voice" in sanitized


def test_apply_speaker_mapping_to_webvtt_content_edge_cases():
    content = (
        "WEBVTT\r\n\r\n"
        "00:00:00.000 --> 00:00:01.000\r\n"
        "<v Speaker 1>Mapped voice</v> <v Speaker 2>Unmapped voice</v>\r\n\r\n"
        "00:00:01.000 --> 00:00:02.000\n"
        "Speaker 1: Mapped prefix\n\n"
        "00:00:02.000 --> 00:00:03.000\n"
        "Speaker 2: Unmapped prefix\n\n"
        "00:00:03.000 --> 00:00:04.000\n"
        "<v.loud Speaker 1>Mapped classed voice</v>\n"
    )

    mapped = apply_speaker_mapping_to_webvtt_content(content, {"Speaker 1": "Alice"})

    assert "<v Alice>Mapped voice</v>" in mapped
    assert "<v Speaker 2>Unmapped voice</v>" in mapped
    assert "Alice: Mapped prefix" in mapped
    assert "Speaker 2: Unmapped prefix" in mapped
    assert "<v.loud Alice>Mapped classed voice</v>" in mapped
    assert apply_speaker_mapping_to_webvtt_content("WEBVTT\n", {}) == "WEBVTT\n"
