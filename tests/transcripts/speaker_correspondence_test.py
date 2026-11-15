"""Refuse ambiguous speaker starts before staging any public format."""

import copy

import pytest

from cast.transcripts import parsing, services
from tests.known_speaker_apply_test import DOTE, PODLOVE, SPEAKERS, VTT, make_transcript


@pytest.mark.django_db
@pytest.mark.parametrize("conflict", ["name", "reject", "same"])
@pytest.mark.parametrize("reverse", [False, True])
def test_rounded_suggestion_collision_preserves_every_artifact(audio, mocker, conflict, reverse):
    speakers = copy.deepcopy(SPEAKERS)
    duplicate = {**speakers["segments"][0], "start": 10.0001}
    if conflict == "name":
        duplicate["speaker"] = "Synthetic other"
    elif conflict == "reject":
        duplicate["editor_decision"] = {"action": "reject"}
    speakers["segments"].append(duplicate)
    if reverse:
        speakers["segments"].reverse()
    transcript = make_transcript(audio, podlove=PODLOVE, dote=DOTE, vtt=VTT, speakers=speakers)
    assert_refused_without_staging(transcript, mocker)


@pytest.mark.django_db
@pytest.mark.parametrize("field", ["podlove", "dote", "vtt"])
@pytest.mark.parametrize("reject", [False, True])
def test_duplicate_destination_refuses_speaker_apply(audio, mocker, field, reject):
    podlove, dote = copy.deepcopy(PODLOVE), copy.deepcopy(DOTE)
    vtt = VTT
    if field == "podlove":
        podlove["transcripts"].append(copy.deepcopy(podlove["transcripts"][0]))
    elif field == "dote":
        dote["lines"].append(copy.deepcopy(dote["lines"][0]))
    else:
        vtt += "00:00:10.000 --> 00:00:11.000\nSynthetic duplicate\n\n"
    speakers = copy.deepcopy(SPEAKERS)
    if reject:
        speakers["segments"][0]["editor_decision"] = {"action": "reject"}
    transcript = make_transcript(audio, podlove=podlove, dote=dote, vtt=vtt, speakers=speakers)
    assert_refused_without_staging(transcript, mocker)


def assert_refused_without_staging(transcript, mocker):
    before = {name: transcript._read_file_bytes(name) for name in services.EDITOR_ARTIFACT_FIELDS}
    stage = mocker.spy(transcript, "_save_file_content")
    with pytest.raises(parsing.TranscriptArtifactError, match="ambiguous.*start"):
        transcript.apply_known_speaker_suggestions()
    stage.assert_not_called()
    assert {name: transcript._read_file_bytes(name) for name in services.EDITOR_ARTIFACT_FIELDS} == before


@pytest.mark.django_db
def test_unique_correspondence_updates_all_formats(audio):
    transcript = make_transcript(audio, podlove=PODLOVE, dote=DOTE, vtt=VTT, speakers=SPEAKERS)
    assert transcript.apply_known_speaker_suggestions() == 9
    assert transcript.podlove_data["transcripts"][0]["speaker"] == "Johannes"
    assert transcript.dote_data["lines"][0]["speakerDesignation"] == "Johannes"
    assert "<v Johannes>" in transcript._load_text_file("vtt")


@pytest.mark.django_db
@pytest.mark.parametrize("malformed", ["boolean", "duplicate"])
def test_segment_review_refuses_unsafe_correspondence_before_sidecar_write(audio, mocker, malformed):
    podlove, speakers = copy.deepcopy(PODLOVE), copy.deepcopy(SPEAKERS)
    if malformed == "boolean":
        podlove["transcripts"].append({"start_ms": True, "text": "Malformed"})
    else:
        speakers["segments"].append({"start": 10.0001, "speaker": "Synthetic other"})
    transcript = make_transcript(audio, podlove=podlove, dote=DOTE, vtt=VTT, speakers=speakers)
    before = {name: transcript._read_file_bytes(name) for name in services.EDITOR_ARTIFACT_FIELDS}
    stage = mocker.spy(transcript, "_save_file_content")
    with pytest.raises(parsing.TranscriptArtifactError):
        transcript.save_known_speaker_editor_decisions({0: {"action": "reject"}})
    stage.assert_not_called()
    assert {name: transcript._read_file_bytes(name) for name in services.EDITOR_ARTIFACT_FIELDS} == before
