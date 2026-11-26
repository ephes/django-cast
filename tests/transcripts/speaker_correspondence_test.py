"""Refuse ambiguous speaker starts before staging any public format."""

import copy
from io import BytesIO
from unittest.mock import patch

import pytest
from django.core.files import File

from cast.transcripts import parsing, services
from tests.transcripts.known_speaker_apply_helpers import DOTE, PODLOVE, SPEAKERS, VTT, make_transcript


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


@pytest.mark.django_db
@pytest.mark.parametrize("start", [10**400, float("nan"), float("inf"), 1e308, -1e-10, True, None, "bad"])
def test_invalid_suggestion_starts_do_not_influence_smoothing(audio, start):
    speakers = copy.deepcopy(SPEAKERS)
    speakers["segments"][0]["start"] = "10.0"  # Legacy numeric strings still match.
    speakers["segments"].insert(1, {"start": start, "speaker": "Synthetic invalid"})
    transcript = make_transcript(audio, podlove=PODLOVE, dote=DOTE, vtt=VTT, speakers=speakers)

    assert services.resolve_speaker_application(transcript, transcript.get_speaker_suggestions(), smooth=True) == (
        {10000: "Johannes", 12500: "Johannes", 15000: "Dominik"},
        set(),
    )
    assert transcript.apply_known_speaker_suggestions() == 9
    assert transcript.podlove_data["transcripts"][1]["speaker"] == "Johannes"


@pytest.mark.django_db
@pytest.mark.parametrize("operation", ["apply", "rename", "passage", "decisions"])
@pytest.mark.parametrize(
    "error", [FileNotFoundError, OSError, UnicodeDecodeError], ids=["missing", "storage", "encoding"]
)
def test_unreadable_webvtt_refuses_cross_format_speaker_edits(audio, mocker, operation, error):
    podlove, dote = copy.deepcopy(PODLOVE), copy.deepcopy(DOTE)
    podlove["transcripts"][0].update(speaker="Synthetic old", voice="Synthetic old")
    dote["lines"][0]["speakerDesignation"] = "Synthetic old"
    vtt = VTT.replace("\na\n", "\n<v Synthetic old>a</v>\n")
    transcript = make_transcript(audio, podlove=podlove, dote=dote, vtt=vtt, speakers=SPEAKERS)
    expected = services.artifact_state(transcript)
    before = {name: transcript._read_file_bytes(name) for name in services.EDITOR_ARTIFACT_FIELDS}
    storage = transcript.vtt.storage
    original_open = storage.open

    def open_artifact(name, mode="rb"):
        if name == expected["vtt"]:
            if error is UnicodeDecodeError:
                return File(BytesIO(b"\xff"))
            raise error("Synthetic storage failure")
        return original_open(name, mode)

    stage = mocker.spy(transcript, "_save_file_content")
    with patch.object(storage, "open", side_effect=open_artifact):
        assert transcript._load_text_file("vtt") == ""
        with pytest.raises(parsing.TranscriptArtifactError, match="WebVTT"):
            if operation == "apply":
                transcript.apply_known_speaker_suggestions()
            elif operation == "rename":
                transcript.rewrite_speaker_labels({"Synthetic old": "Synthetic new"})
            elif operation == "passage":
                transcript.change_passage_speaker(10000, "Synthetic new")
            else:
                transcript.save_known_speaker_editor_decisions({0: {"action": "reject"}})
    stage.assert_not_called()
    transcript.refresh_from_db()
    assert services.artifact_state(transcript) == expected
    assert {name: transcript._read_file_bytes(name) for name in services.EDITOR_ARTIFACT_FIELDS} == before


@pytest.mark.django_db
def test_speaker_edit_webvtt_read_stops_at_byte_ceiling(audio, monkeypatch):
    transcript = make_transcript(audio, podlove=PODLOVE, vtt=VTT, speakers=SPEAKERS)
    consumed = 0
    limit = 10

    class GrowingFile(BytesIO):
        def read(self, size=-1):
            nonlocal consumed
            assert 0 < size <= limit + 1 - consumed
            chunk = b" " * min(size, 3)
            consumed += len(chunk)
            return chunk

    storage = transcript.vtt.storage
    original_open = storage.open
    monkeypatch.setattr(parsing, "MAX_EDITOR_WEBVTT_BYTES", limit)
    monkeypatch.setattr(
        storage, "open", lambda name, mode: GrowingFile() if name == transcript.vtt.name else original_open(name, mode)
    )

    with pytest.raises(parsing.TranscriptArtifactError, match="Stored WebVTT exceeds"):
        transcript.apply_known_speaker_suggestions()
    assert consumed == limit + 1
