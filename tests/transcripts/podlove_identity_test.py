"""Boolean JSON values must never alias integer millisecond identities."""

import copy

import pytest

from cast.transcripts import corrections, parsing, podlove, services
from tests.known_speaker_apply_test import make_transcript


@pytest.mark.parametrize("invalid", [True, False, -1, 1.0, "1", None])
def test_podlove_identity_uses_only_nonnegative_integers(invalid):
    data = {"transcripts": [{"start_ms": invalid, "text": "invalid"}, {"start_ms": 1, "text": "valid"}]}
    assert podlove.get_texts(data) == [(1, "valid")]
    assert podlove.set_texts(data, {0: "new", 1: "new", -1: "new"}) == 1
    assert data["transcripts"][0]["text"] == "invalid"
    assert podlove.apply_suggestions(data, {0: "Synthetic", 1: "Synthetic", -1: "Synthetic"}) == 1
    data["transcripts"][0]["speaker"] = "untouched"
    assert podlove.clear_suggestions(data, {0, 1, -1})[0] == 1
    assert data["transcripts"][0]["speaker"] == "untouched"


@pytest.mark.django_db
@pytest.mark.parametrize("boolean", [True, False])
@pytest.mark.parametrize("operation", ["correction", "speaker"])
def test_boolean_podlove_identity_refuses_mutation_before_staging(episode, mocker, boolean, operation):
    data = {
        "transcripts": [
            {"start_ms": 0, "text": "Synthetic zero"},
            {"start_ms": 1, "text": "Synthetic one"},
            {"start_ms": boolean, "text": "Malformed neighbor"},
        ]
    }
    transcript = make_transcript(
        episode.podcast_audio,
        podlove=copy.deepcopy(data),
        speakers={"segments": [{"start": 0, "speaker": "Synthetic"}, {"start": 0.001, "speaker": "Synthetic"}]},
    )
    before = {name: transcript._read_file_bytes(name) for name in services.EDITOR_ARTIFACT_FIELDS}
    stage = mocker.spy(transcript, "_save_file_content")
    with pytest.raises(parsing.TranscriptArtifactError, match="millisecond"):
        if operation == "correction":
            corrections.refresh_transcript_corrections(transcript, episode=episode)
        else:
            transcript.apply_known_speaker_suggestions()
    stage.assert_not_called()
    assert {name: transcript._read_file_bytes(name) for name in services.EDITOR_ARTIFACT_FIELDS} == before


def test_speaker_review_text_cannot_come_from_boolean_neighbor():
    from types import SimpleNamespace

    from cast.views.transcript import get_known_speaker_text_by_start_ms

    transcript = SimpleNamespace(
        podlove_data={
            "transcripts": [
                {"start_ms": True, "text": "Invalid one"},
                {"start_ms": False, "text": "Invalid zero"},
                {"start_ms": 0, "text": "Valid zero"},
                {"start_ms": 1, "text": "Valid one"},
            ]
        },
        dote_data={},
    )
    assert get_known_speaker_text_by_start_ms(transcript) == {0: "Valid zero", 1: "Valid one"}
