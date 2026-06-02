"""Tests for reviewing and applying known-speaker suggestions to public output."""

import copy
import json

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse

from cast.forms import KnownSpeakerSegmentReviewForm
from cast.models import Transcript
from cast.models.transcript import (
    KNOWN_SPEAKER_DECISION_CORRECT,
    KNOWN_SPEAKER_DECISION_REJECT,
    KNOWN_SPEAKER_EDITOR_DECISION_FIELD,
    _dote_timestamp_to_ms,
    _webvtt_timestamp_to_ms,
)
from cast.views.transcript import get_known_speaker_review_rows, get_known_speaker_text_by_start_ms


def make_transcript(audio, *, podlove=None, dote=None, vtt=None, speakers=None):
    transcript = Transcript.objects.create(audio=audio)
    if podlove is not None:
        transcript.podlove.save("t.podlove.json", ContentFile(json.dumps(podlove).encode()), save=False)
    if dote is not None:
        transcript.dote.save("t.dote.json", ContentFile(json.dumps(dote).encode()), save=False)
    if vtt is not None:
        transcript.vtt.save("t.vtt", ContentFile(vtt.encode()), save=False)
    if speakers is not None:
        transcript.speakers.save("t.speakers.json", ContentFile(json.dumps(speakers).encode()), save=False)
    transcript.save()
    return transcript


PODLOVE = {
    "version": 1,
    "transcripts": [
        {"start": "00:00:10.000", "start_ms": 10000, "speaker": "", "voice": "", "text": "a"},
        {"start": "00:00:12.500", "start_ms": 12500, "speaker": "", "voice": "", "text": "b"},
        {"start": "00:00:15.000", "start_ms": 15000, "speaker": "", "voice": "", "text": "c"},
    ],
}
DOTE = {
    "lines": [
        {"startTime": "00:00:10,000", "speakerDesignation": "", "text": "a"},
        {"startTime": "00:00:12,500", "speakerDesignation": "", "text": "b"},
        {"startTime": "00:00:15,000", "speakerDesignation": "", "text": "c"},
    ]
}
VTT = (
    "WEBVTT\n\n"
    "00:00:10.000 --> 00:00:12.500\n"
    "a\n\n"
    "00:00:12.500 --> 00:00:15.000\n"
    "b\n\n"
    "00:00:15.000 --> 00:00:16.000\n"
    "c\n\n"
    "00:00:20.000 --> 00:00:21.000\n"
    "unmatched\n\n"
)
SPEAKERS = {
    "summary": {"strategy": "pyannote_known_speaker"},
    "segments": [
        {"index": 0, "start": 10.0, "speaker": "Johannes", "speaker_uncertain": False},
        {"index": 1, "start": 12.5, "speaker": None, "speaker_uncertain": True},
        {"index": 2, "start": 15.0, "speaker": "Dominik", "speaker_uncertain": False},
    ],
}


def test_dote_timestamp_to_ms():
    assert _dote_timestamp_to_ms("00:00:10,000") == 10000
    assert _dote_timestamp_to_ms("01:02:03.500") == 3723500
    assert _dote_timestamp_to_ms("bad") is None
    assert _dote_timestamp_to_ms(None) is None


def test_webvtt_timestamp_to_ms():
    assert _webvtt_timestamp_to_ms("00:00:10.000") == 10000
    assert _webvtt_timestamp_to_ms("01:02:03.500") == 3723500
    assert _webvtt_timestamp_to_ms("00:10.5") == 10500
    assert _webvtt_timestamp_to_ms("bad") is None
    assert _webvtt_timestamp_to_ms(None) is None


@pytest.mark.django_db
def test_review_summary_counts_confident_and_uncertain(audio):
    transcript = make_transcript(audio, speakers=SPEAKERS)
    summary = transcript.known_speaker_review_summary()
    assert summary["total"] == 3
    assert summary["confident"] == 2
    assert summary["uncertain"] == 1
    assert summary["by_speaker"] == {"Dominik": 1, "Johannes": 1}
    assert summary["metadata"]["strategy"] == "pyannote_known_speaker"


@pytest.mark.django_db
def test_review_summary_ignores_confident_segment_without_name(audio):
    # A non-uncertain segment with no resolved name is counted as confident but
    # contributes no speaker to the distribution.
    speakers = {
        "segments": [
            {"index": 0, "start": 1.0, "speaker": None, "speaker_uncertain": False},
            {"index": 1, "start": 2.0, "speaker": "Ronny", "speaker_uncertain": False},
        ]
    }
    transcript = make_transcript(audio, speakers=speakers)
    summary = transcript.known_speaker_review_summary()
    assert summary["confident"] == 2
    assert summary["by_speaker"] == {"Ronny": 1}


def test_known_speaker_editor_decision_normalization():
    assert Transcript._normalize_known_speaker_editor_decision(None) is None
    assert Transcript._normalize_known_speaker_editor_decision({"action": "unknown", "speaker": "Alice"}) is None
    assert Transcript._normalize_known_speaker_editor_decision({"action": "correct", "speaker": "  "}) is None
    assert Transcript._normalize_known_speaker_editor_decision({"action": "reject", "speaker": "Alice"}) == {
        "action": "reject",
        "speaker": "",
    }
    assert Transcript._normalize_known_speaker_editor_decision({"action": "approve", "speaker": " Alice "}) == {
        "action": "approve",
        "speaker": "Alice",
    }


@pytest.mark.django_db
def test_save_known_speaker_editor_decisions_round_trips_and_preserves_raw_metadata(audio):
    speakers = {
        "summary": {"strategy": "pyannote_known_speaker"},
        "segments": [
            {
                "index": 0,
                "start": 10.0,
                "speaker": "Johannes",
                "speaker_uncertain": False,
                "candidates": [{"speaker": "Johannes", "confidence": 0.97}, {"speaker": "Ronny"}],
                "confidence": 0.97,
                "margin": 0.25,
                "raw_speaker": "SPEAKER_00",
            },
            "not-a-segment",
            {
                "index": 1,
                "start": 12.5,
                "speaker": "Dominik",
                "speaker_uncertain": True,
                "confidence": 0.51,
                "margin": 0.03,
                "raw_speaker": "SPEAKER_01",
                KNOWN_SPEAKER_EDITOR_DECISION_FIELD: {"action": "correct", "speaker": "Old"},
            },
            {
                "index": 2,
                "start": 15.0,
                "speaker": None,
                "speaker_uncertain": True,
                KNOWN_SPEAKER_EDITOR_DECISION_FIELD: {"action": "unknown", "speaker": "Ignored"},
            },
        ],
    }
    transcript = make_transcript(audio, speakers=speakers)

    changed = transcript.save_known_speaker_editor_decisions(
        {
            0: {"action": KNOWN_SPEAKER_DECISION_CORRECT, "speaker": " Ronny "},
            1: {"action": KNOWN_SPEAKER_DECISION_REJECT, "speaker": ""},
            2: None,
        }
    )

    assert changed == 3
    saved_segments = transcript.speakers_data["segments"]
    assert saved_segments[0]["speaker"] == "Johannes"
    assert saved_segments[0]["speaker_uncertain"] is False
    assert saved_segments[0]["candidates"] == [{"speaker": "Johannes", "confidence": 0.97}, {"speaker": "Ronny"}]
    assert saved_segments[0]["confidence"] == 0.97
    assert saved_segments[0]["margin"] == 0.25
    assert saved_segments[0]["raw_speaker"] == "SPEAKER_00"
    assert saved_segments[0][KNOWN_SPEAKER_EDITOR_DECISION_FIELD] == {
        "action": KNOWN_SPEAKER_DECISION_CORRECT,
        "speaker": "Ronny",
    }
    assert saved_segments[1] == "not-a-segment"
    assert saved_segments[2]["speaker"] == "Dominik"
    assert saved_segments[2]["speaker_uncertain"] is True
    assert saved_segments[2]["confidence"] == 0.51
    assert saved_segments[2]["margin"] == 0.03
    assert saved_segments[2]["raw_speaker"] == "SPEAKER_01"
    assert saved_segments[2][KNOWN_SPEAKER_EDITOR_DECISION_FIELD] == {
        "action": KNOWN_SPEAKER_DECISION_REJECT,
        "speaker": "",
    }
    assert KNOWN_SPEAKER_EDITOR_DECISION_FIELD not in saved_segments[3]
    assert transcript.get_known_speaker_editor_decisions() == {
        0: {"action": KNOWN_SPEAKER_DECISION_CORRECT, "speaker": "Ronny"},
        1: {"action": KNOWN_SPEAKER_DECISION_REJECT, "speaker": ""},
    }
    assert (
        transcript.save_known_speaker_editor_decisions({0: saved_segments[0][KNOWN_SPEAKER_EDITOR_DECISION_FIELD]})
        == 0
    )


@pytest.mark.django_db
def test_save_known_speaker_editor_decisions_uses_filtered_segment_positions(audio):
    speakers = {
        "segments": [
            "not-a-segment",
            {"index": 0, "start": 10.0, "speaker": "Johannes", "speaker_uncertain": False},
            {"index": 1, "start": 12.5, "speaker": "Maybe", "speaker_uncertain": True},
        ]
    }
    transcript = make_transcript(audio, speakers=speakers)
    form = KnownSpeakerSegmentReviewForm(
        {
            "action": "review-known-speakers",
            "known_speaker_segment_1": "__blank__",
        },
        segments=transcript.get_speaker_suggestions(),
        contributor_assignments=[],
    )

    assert form.is_valid()
    assert transcript.save_known_speaker_editor_decisions(form.segment_decisions) == 1

    saved_segments = transcript.speakers_data["segments"]
    assert KNOWN_SPEAKER_EDITOR_DECISION_FIELD not in saved_segments[1]
    assert saved_segments[2][KNOWN_SPEAKER_EDITOR_DECISION_FIELD] == {
        "action": KNOWN_SPEAKER_DECISION_REJECT,
        "speaker": "",
    }


@pytest.mark.django_db
def test_save_known_speaker_editor_decisions_without_segments_returns_zero(audio):
    transcript = make_transcript(audio, speakers={"summary": {"strategy": "pyannote_known_speaker"}})
    assert transcript.save_known_speaker_editor_decisions({0: {"action": "reject", "speaker": ""}}) == 0


@pytest.mark.django_db
def test_save_known_speaker_editor_decisions_rolls_back_sidecar_when_save_fails(audio, mocker):
    transcript = make_transcript(audio, speakers=SPEAKERS)
    old_speakers_name = transcript.speakers.name
    storage = transcript.speakers.storage
    original_save = storage.save
    saved_names = []

    def recording_save(name, content, *args, **kwargs):
        saved_name = original_save(name, content, *args, **kwargs)
        saved_names.append(saved_name)
        return saved_name

    mocker.patch.object(storage, "save", side_effect=recording_save)
    mocker.patch.object(Transcript, "save", autospec=True, side_effect=RuntimeError("db save failed"))

    with pytest.raises(RuntimeError, match="db save failed"):
        transcript.save_known_speaker_editor_decisions({0: {"action": KNOWN_SPEAKER_DECISION_REJECT, "speaker": ""}})

    persisted = Transcript.objects.get(pk=transcript.pk)
    assert transcript.speakers.name == old_speakers_name
    assert persisted.speakers.name == old_speakers_name
    assert storage.exists(old_speakers_name)
    assert saved_names
    assert all(not storage.exists(name) for name in saved_names)
    assert persisted.get_known_speaker_editor_decisions() == {}


@pytest.mark.django_db
def test_apply_without_smoothing_labels_confident_only(audio):
    transcript = make_transcript(audio, podlove=PODLOVE, dote=DOTE, speakers=SPEAKERS)

    applied = transcript.apply_known_speaker_suggestions(smooth=False)

    assert applied == 4  # 2 podlove + 2 dote (uncertain middle segment skipped)
    podlove = transcript.podlove_data["transcripts"]
    assert podlove[0]["speaker"] == "Johannes"
    assert podlove[0]["voice"] == "Johannes"
    assert podlove[1]["speaker"] == ""  # uncertain -> not applied
    assert podlove[2]["speaker"] == "Dominik"
    dote = transcript.dote_data["lines"]
    assert dote[0]["speakerDesignation"] == "Johannes"
    assert dote[1]["speakerDesignation"] == ""
    assert dote[2]["speakerDesignation"] == "Dominik"
    # The private sidecar is preserved for audit/re-application.
    assert transcript.get_speaker_suggestions()


@pytest.mark.django_db
def test_apply_smooths_uncertain_segments_by_default(audio):
    transcript = make_transcript(audio, podlove=PODLOVE, dote=DOTE, speakers=SPEAKERS)

    applied = transcript.apply_known_speaker_suggestions()

    # Every segment is labeled: the uncertain middle one carries the previous
    # confident speaker forward so the transcript reads continuously.
    assert applied == 6  # 3 podlove + 3 dote
    podlove = transcript.podlove_data["transcripts"]
    assert [s["speaker"] for s in podlove] == ["Johannes", "Johannes", "Dominik"]
    dote = transcript.dote_data["lines"]
    assert [line["speakerDesignation"] for line in dote] == ["Johannes", "Johannes", "Dominik"]
    # The sidecar still records the segment as uncertain for audit.
    assert transcript.get_speaker_suggestions()[1]["speaker_uncertain"] is True


@pytest.mark.django_db
def test_apply_updates_unlabeled_vtt_by_start_time_with_smoothing(audio):
    transcript = make_transcript(audio, podlove=PODLOVE, dote=DOTE, vtt=VTT, speakers=SPEAKERS)
    with transcript.speakers.open("rb") as speakers_file:
        original_speakers_content = speakers_file.read()

    applied = transcript.apply_known_speaker_suggestions()

    assert applied == 9  # 3 podlove + 3 dote + 3 WebVTT cues
    podlove = transcript.podlove_data["transcripts"]
    assert [segment["speaker"] for segment in podlove] == ["Johannes", "Johannes", "Dominik"]
    dote = transcript.dote_data["lines"]
    assert [line["speakerDesignation"] for line in dote] == ["Johannes", "Johannes", "Dominik"]
    with transcript.vtt.open("r") as vtt_file:
        assert vtt_file.read() == (
            "WEBVTT\n\n"
            "00:00:10.000 --> 00:00:12.500\n"
            "<v Johannes>a\n\n"
            "00:00:12.500 --> 00:00:15.000\n"
            "<v Johannes>b\n\n"
            "00:00:15.000 --> 00:00:16.000\n"
            "<v Dominik>c\n\n"
            "00:00:20.000 --> 00:00:21.000\n"
            "unmatched\n\n"
        )
    with transcript.speakers.open("rb") as speakers_file:
        assert speakers_file.read() == original_speakers_content


@pytest.mark.django_db
def test_apply_known_speaker_suggestions_rolls_back_files_when_save_fails(audio, mocker):
    transcript = make_transcript(audio, podlove=PODLOVE, dote=DOTE, speakers=SPEAKERS)
    old_podlove_name = transcript.podlove.name
    old_dote_name = transcript.dote.name
    storage = transcript.podlove.storage
    original_save = storage.save
    saved_names = []

    def recording_save(name, content, *args, **kwargs):
        saved_name = original_save(name, content, *args, **kwargs)
        saved_names.append(saved_name)
        return saved_name

    mocker.patch.object(storage, "save", side_effect=recording_save)
    mocker.patch.object(Transcript, "save", autospec=True, side_effect=RuntimeError("db save failed"))

    with pytest.raises(RuntimeError, match="db save failed"):
        transcript.apply_known_speaker_suggestions()

    persisted = Transcript.objects.get(pk=transcript.pk)
    assert transcript.podlove.name == old_podlove_name
    assert transcript.dote.name == old_dote_name
    assert persisted.podlove.name == old_podlove_name
    assert persisted.dote.name == old_dote_name
    assert storage.exists(old_podlove_name)
    assert storage.exists(old_dote_name)
    assert saved_names
    assert all(not storage.exists(name) for name in saved_names)
    assert persisted.podlove_data["transcripts"][0]["speaker"] == ""
    assert persisted.dote_data["lines"][0]["speakerDesignation"] == ""


@pytest.mark.django_db
def test_apply_replaces_existing_vtt_voice_labels_by_start_time(audio):
    speakers = {
        "segments": [
            {"index": 0, "start": 10.0, "speaker": "Johannes", "speaker_uncertain": False},
            {"index": 1, "start": 15.0, "speaker": "Dominik", "speaker_uncertain": False},
        ]
    }
    vtt = (
        "WEBVTT\r\n\r\n"
        "cue-1\r\n"
        "00:00:10.000 --> 00:00:11.000\r\n"
        "<v Speaker 0>a</v>\r\n\r\n"
        "00:00:15.000 --> 00:00:16.000\n"
        "<v Speaker 0>c\n"
    )
    transcript = make_transcript(audio, vtt=vtt, speakers=speakers)

    assert transcript.apply_known_speaker_suggestions() == 2

    with transcript.vtt.open("rb") as vtt_file:
        assert vtt_file.read().decode("utf-8") == (
            "WEBVTT\r\n\r\n"
            "cue-1\r\n"
            "00:00:10.000 --> 00:00:11.000\r\n"
            "<v Johannes>a</v>\r\n\r\n"
            "00:00:15.000 --> 00:00:16.000\n"
            "<v Dominik>c\n"
        )


@pytest.mark.django_db
def test_apply_leaves_vtt_unchanged_without_matching_cue(audio):
    speakers = {"segments": [{"index": 0, "start": 99.0, "speaker": "Johannes", "speaker_uncertain": False}]}
    transcript = make_transcript(audio, vtt=VTT, speakers=speakers)

    assert transcript.apply_known_speaker_suggestions() == 0

    with transcript.vtt.open("r") as vtt_file:
        assert vtt_file.read() == VTT


@pytest.mark.django_db
def test_apply_counts_already_labeled_matching_vtt_without_rewriting(audio):
    speakers = {"segments": [{"index": 0, "start": 10.0, "speaker": "Johannes", "speaker_uncertain": False}]}
    vtt = "WEBVTT\n\n00:00:10.000 --> 00:00:11.000\n<v Johannes>a\n"
    transcript = make_transcript(audio, vtt=vtt, speakers=speakers)

    assert transcript.apply_known_speaker_suggestions() == 1

    with transcript.vtt.open("r") as vtt_file:
        assert vtt_file.read() == vtt


def test_apply_webvtt_skips_matched_cue_without_payload():
    content = "WEBVTT\n\n00:00:10.000 --> 00:00:11.000\n\n"

    rewritten_content, applied, changed = Transcript._apply_suggestions_to_webvtt_content(content, {10000: "Johannes"})

    assert applied == 0
    assert not changed
    assert rewritten_content == content


@pytest.mark.django_db
def test_apply_smoothing_backfills_leading_uncertain(audio):
    # A leading uncertain segment is backfilled from the first confident speaker.
    podlove = {
        "transcripts": [
            {"start_ms": 1000, "speaker": "", "voice": "", "text": "a"},
            {"start_ms": 2000, "speaker": "", "voice": "", "text": "b"},
        ]
    }
    speakers = {
        "segments": [
            {"index": 0, "start": 1.0, "speaker": None, "speaker_uncertain": True},
            {"index": 1, "start": 2.0, "speaker": "Ronny", "speaker_uncertain": False},
        ]
    }
    transcript = make_transcript(audio, podlove=podlove, speakers=speakers)
    transcript.apply_known_speaker_suggestions()
    assert [s["speaker"] for s in transcript.podlove_data["transcripts"]] == ["Ronny", "Ronny"]


@pytest.mark.django_db
def test_apply_returns_zero_without_confident_suggestions(audio):
    speakers = {"segments": [{"index": 0, "start": 10.0, "speaker": None, "speaker_uncertain": True}]}
    transcript = make_transcript(audio, podlove=PODLOVE, dote=DOTE, speakers=speakers)
    assert transcript.apply_known_speaker_suggestions() == 0
    assert transcript.podlove_data["transcripts"][0]["speaker"] == ""


@pytest.mark.django_db
def test_apply_editor_decision_overrides_smoothing_for_all_formats(audio):
    speakers = copy.deepcopy(SPEAKERS)
    speakers["segments"][1]["speaker"] = "Dominik"
    speakers["segments"][1][KNOWN_SPEAKER_EDITOR_DECISION_FIELD] = {
        "action": KNOWN_SPEAKER_DECISION_CORRECT,
        "speaker": "Ronny",
    }
    transcript = make_transcript(audio, podlove=PODLOVE, dote=DOTE, vtt=VTT, speakers=speakers)

    applied = transcript.apply_known_speaker_suggestions()

    assert applied == 9
    podlove = transcript.podlove_data["transcripts"]
    assert [segment["speaker"] for segment in podlove] == ["Johannes", "Ronny", "Dominik"]
    dote = transcript.dote_data["lines"]
    assert [line["speakerDesignation"] for line in dote] == ["Johannes", "Ronny", "Dominik"]
    with transcript.vtt.open("r") as vtt_file:
        assert "<v Ronny>b" in vtt_file.read()


@pytest.mark.django_db
def test_apply_reject_decision_clears_existing_public_labels_by_start_time(audio):
    podlove = copy.deepcopy(PODLOVE)
    podlove["transcripts"].append("not-a-segment")
    podlove["transcripts"].append({"start_ms": 99999, "speaker": "Other", "voice": "Other", "text": "unmatched"})
    for segment in podlove["transcripts"][:3]:
        segment["speaker"] = "Existing"
        segment["voice"] = "Existing"
    dote = copy.deepcopy(DOTE)
    dote["lines"].append("not-a-line")
    dote["lines"].append({"startTime": "00:01:39,999", "speakerDesignation": "Other", "text": "unmatched"})
    for line in dote["lines"][:3]:
        line["speakerDesignation"] = "Existing"
    vtt = (
        "WEBVTT\n\n"
        "00:00:10.000 --> 00:00:12.500\n"
        "<v Existing>a</v>\n\n"
        "00:00:12.500 --> 00:00:15.000\n"
        "<v Existing>b</v>\n\n"
        "00:00:15.000 --> 00:00:16.000\n"
        "<v Existing>c</v>\n\n"
    )
    speakers = copy.deepcopy(SPEAKERS)
    speakers["segments"][1][KNOWN_SPEAKER_EDITOR_DECISION_FIELD] = {
        "action": KNOWN_SPEAKER_DECISION_REJECT,
        "speaker": "",
    }
    transcript = make_transcript(audio, podlove=podlove, dote=dote, vtt=vtt, speakers=speakers)

    applied = transcript.apply_known_speaker_suggestions()

    assert applied == 9
    podlove = transcript.podlove_data["transcripts"]
    assert [segment["speaker"] for segment in podlove[:3]] == ["Johannes", "", "Dominik"]
    assert [segment["voice"] for segment in podlove[:3]] == ["Johannes", "", "Dominik"]
    dote = transcript.dote_data["lines"]
    assert [line["speakerDesignation"] for line in dote[:3]] == ["Johannes", "", "Dominik"]
    with transcript.vtt.open("r") as vtt_file:
        assert vtt_file.read() == (
            "WEBVTT\n\n"
            "00:00:10.000 --> 00:00:12.500\n"
            "<v Johannes>a</v>\n\n"
            "00:00:12.500 --> 00:00:15.000\n"
            "b\n\n"
            "00:00:15.000 --> 00:00:16.000\n"
            "<v Dominik>c</v>\n\n"
        )


@pytest.mark.django_db
def test_apply_reject_decision_counts_already_blank_public_entries(audio):
    speakers = {
        "segments": [
            {
                "index": 0,
                "start": 10.0,
                "speaker": None,
                "speaker_uncertain": True,
                KNOWN_SPEAKER_EDITOR_DECISION_FIELD: {
                    "action": KNOWN_SPEAKER_DECISION_REJECT,
                    "speaker": "",
                },
            }
        ]
    }
    transcript = make_transcript(audio, podlove=PODLOVE, dote=DOTE, vtt=VTT, speakers=speakers)

    assert transcript.apply_known_speaker_suggestions() == 3
    assert transcript.podlove_data["transcripts"][0]["speaker"] == ""
    assert transcript.dote_data["lines"][0]["speakerDesignation"] == ""
    with transcript.vtt.open("r") as vtt_file:
        assert vtt_file.read() == VTT


@pytest.mark.django_db
def test_apply_skips_segment_with_unparseable_start(audio):
    speakers = {"segments": [{"index": 0, "start": "oops", "speaker": "X", "speaker_uncertain": False}]}
    transcript = make_transcript(audio, podlove=PODLOVE, dote=DOTE, speakers=speakers)
    assert transcript.apply_known_speaker_suggestions() == 0


@pytest.mark.django_db
def test_apply_without_podlove_or_dote_files(audio):
    transcript = make_transcript(audio, speakers=SPEAKERS)
    assert transcript.apply_known_speaker_suggestions() == 0


@pytest.mark.django_db
def test_apply_ignores_podlove_segment_without_int_start_ms(audio):
    podlove = {"transcripts": [{"start_ms": "10000", "speaker": "", "text": "a"}, "not-a-dict"]}
    transcript = make_transcript(audio, podlove=podlove, speakers=SPEAKERS)
    assert transcript.apply_known_speaker_suggestions() == 0


@pytest.mark.django_db
def test_apply_ignores_dote_line_without_startTime(audio):
    dote = {"lines": [{"speakerDesignation": "", "text": "a"}, "not-a-dict"]}
    transcript = make_transcript(audio, dote=dote, speakers=SPEAKERS)
    assert transcript.apply_known_speaker_suggestions() == 0


@pytest.mark.django_db
def test_apply_handles_non_list_transcript_bodies(audio):
    transcript = make_transcript(audio, podlove={"transcripts": "x"}, dote={"lines": "x"}, speakers=SPEAKERS)
    assert transcript.apply_known_speaker_suggestions() == 0


@pytest.mark.django_db
def test_apply_reject_handles_non_list_transcript_bodies(audio):
    speakers = {
        "segments": [
            {
                "index": 0,
                "start": 10.0,
                "speaker": None,
                "speaker_uncertain": True,
                KNOWN_SPEAKER_EDITOR_DECISION_FIELD: {
                    "action": KNOWN_SPEAKER_DECISION_REJECT,
                    "speaker": "",
                },
            }
        ]
    }
    transcript = make_transcript(audio, podlove={"transcripts": "x"}, dote={"lines": "x"}, speakers=speakers)
    assert transcript.apply_known_speaker_suggestions() == 0


def test_clear_webvtt_skips_matched_cue_without_payload():
    content = "WEBVTT\n\n00:00:10.000 --> 00:00:11.000\n\n"

    rewritten_content, applied, changed = Transcript._clear_suggestions_from_webvtt_content(content, {10000})

    assert applied == 0
    assert not changed
    assert rewritten_content == content


def test_clear_webvtt_counts_unlabeled_payload_without_rewriting():
    content = "WEBVTT\n\n00:00:10.000 --> 00:00:11.000\na\n\n"

    rewritten_content, applied, changed = Transcript._clear_suggestions_from_webvtt_content(content, {10000})

    assert applied == 1
    assert not changed
    assert rewritten_content == content


@pytest.mark.django_db
def test_known_speaker_segment_review_form_cleans_segment_decisions(audio):
    segments = [
        {"index": 0, "speaker": "Johannes", "candidates": None},
        {"index": 1, "speaker": None, "candidates": [{"speaker": "Candidate"}, {"name": "Named"}, "Loose"]},
        {"index": 2, "speaker": "Dominik"},
        {
            "index": 3,
            "speaker": "Ronny",
            KNOWN_SPEAKER_EDITOR_DECISION_FIELD: {
                "action": KNOWN_SPEAKER_DECISION_REJECT,
                "speaker": "",
            },
        },
    ]
    initial_form = KnownSpeakerSegmentReviewForm(
        segments=segments,
        contributor_assignments=[],
        multiple_episodes=True,
    )
    assert initial_form.fields["known_speaker_segment_3"].initial == "__blank__"
    assert [choice[1] for choice in initial_form.fields["known_speaker_segment_0"].choices] == [
        "Use bulk result",
        "Leave blank",
        "Johannes",
        "Candidate",
        "Named",
        "Loose",
        "Dominik",
        "Ronny",
    ]
    assert initial_form.speaker_value_by_name["Candidate"] == "speaker:Candidate"

    form = KnownSpeakerSegmentReviewForm(
        {
            "action": "review-known-speakers",
            "known_speaker_segment_0": initial_form.speaker_value_by_name["Johannes"],
            "known_speaker_segment_1": "__blank__",
            "known_speaker_segment_2": initial_form.speaker_value_by_name["Candidate"],
        },
        segments=segments,
        contributor_assignments=[],
    )

    assert form.is_valid()
    assert form.segment_decisions == {
        0: {"action": "approve", "speaker": "Johannes"},
        1: {"action": "reject", "speaker": ""},
        2: {"action": "correct", "speaker": "Candidate"},
        3: None,
    }


@pytest.mark.django_db
def test_known_speaker_segment_review_form_initializes_corrected_decision(audio):
    segments = [
        {
            "index": 0,
            "speaker": "Johannes",
            "candidates": ["Ronny"],
            KNOWN_SPEAKER_EDITOR_DECISION_FIELD: {
                "action": KNOWN_SPEAKER_DECISION_CORRECT,
                "speaker": "Ronny",
            },
        }
    ]

    form = KnownSpeakerSegmentReviewForm(segments=segments, contributor_assignments=[])

    assert form.fields["known_speaker_segment_0"].initial == form.speaker_value_by_name["Ronny"]


@pytest.mark.django_db
def test_known_speaker_text_by_start_ms_uses_podlove_and_dote_text(audio):
    transcript = make_transcript(
        audio,
        podlove={
            "transcripts": [
                "not-a-segment",
                {"start_ms": 10000, "text": "Podlove wins"},
                {"start_ms": "12500", "text": "bad start"},
                {"start_ms": 15000, "text": ""},
            ]
        },
        dote={
            "lines": [
                "not-a-line",
                {"startTime": "00:00:10,000", "text": "DOTe duplicate"},
                {"startTime": "00:00:12,500", "text": "DOTe fallback"},
                {"startTime": "bad", "text": "bad start"},
                {"startTime": "00:00:15,000", "text": ""},
            ]
        },
    )

    assert get_known_speaker_text_by_start_ms(transcript) == {
        10000: "Podlove wins",
        12500: "DOTe fallback",
    }


@pytest.mark.django_db
def test_known_speaker_text_by_start_ms_ignores_non_list_transcripts(audio):
    transcript = make_transcript(audio, podlove={"transcripts": "x"}, dote={"lines": "x"})
    assert get_known_speaker_text_by_start_ms(transcript) == {}


@pytest.mark.django_db
def test_known_speaker_review_rows_use_sidecar_text_without_transcript_fallback(audio):
    transcript = make_transcript(audio, podlove=PODLOVE, dote=DOTE)
    form = KnownSpeakerSegmentReviewForm(
        segments=[
            {
                "start": "not-a-time",
                "speaker": "Johannes",
                "speaker_uncertain": False,
                "text": "Sidecar text is already present.",
                "confidence": 0.99,
                "margin": 0.8,
            }
        ],
        contributor_assignments=[],
    )

    row = get_known_speaker_review_rows(transcript, form)[0]
    assert row["confidence"] == 0.99
    assert row["field"].name == "known_speaker_segment_0"
    assert row["margin"] == 0.8
    assert row["speaker"] == "Johannes"
    assert row["text"] == "Sidecar text is already present."
    assert row["timestamp_label"] == ""
    assert row["uncertain"] is False


@pytest.mark.django_db
class TestKnownSpeakerReviewView:
    def test_edit_page_shows_review_panel(self, admin_client, audio):
        transcript = make_transcript(audio, podlove=PODLOVE, dote=DOTE, speakers=SPEAKERS)
        response = admin_client.get(reverse("cast-transcript:edit", args=(transcript.id,)))
        assert response.status_code == 200
        assert b"Known-speaker suggestions" in response.content
        assert b"Save segment decisions" in response.content

    def test_apply_action_labels_public_output(self, admin_client, audio):
        transcript = make_transcript(audio, podlove=PODLOVE, dote=DOTE, speakers=SPEAKERS)
        response = admin_client.post(
            reverse("cast-transcript:edit", args=(transcript.id,)),
            {"action": "apply-known-speakers"},
        )
        assert response.status_code == 302

    def test_review_action_corrects_segment_and_preserves_raw_sidecar(self, admin_client, audio):
        speakers = copy.deepcopy(SPEAKERS)
        speakers["segments"][1]["speaker"] = "Johannes"
        speakers["segments"][1]["candidates"] = [{"speaker": "Ronny"}]
        speakers["segments"][1]["confidence"] = 0.52
        transcript = make_transcript(audio, podlove=PODLOVE, dote=DOTE, vtt=VTT, speakers=speakers)
        form = KnownSpeakerSegmentReviewForm(
            segments=transcript.get_speaker_suggestions(),
            contributor_assignments=[],
        )

        response = admin_client.post(
            reverse("cast-transcript:edit", args=(transcript.id,)),
            {
                "action": "review-known-speakers",
                "known_speaker_segment_1": form.speaker_value_by_name["Ronny"],
            },
        )

        assert response.status_code == 302
        transcript.refresh_from_db()
        assert transcript.podlove_data["transcripts"][1]["speaker"] == "Ronny"
        assert transcript.dote_data["lines"][1]["speakerDesignation"] == "Ronny"
        with transcript.vtt.open("r") as vtt_file:
            assert "<v Ronny>b" in vtt_file.read()
        segment = transcript.speakers_data["segments"][1]
        assert segment["speaker"] == "Johannes"
        assert segment["candidates"] == [{"speaker": "Ronny"}]
        assert segment["confidence"] == 0.52
        assert segment[KNOWN_SPEAKER_EDITOR_DECISION_FIELD] == {
            "action": KNOWN_SPEAKER_DECISION_CORRECT,
            "speaker": "Ronny",
        }

    def test_review_action_rejects_segment_to_blank(self, admin_client, audio):
        podlove = copy.deepcopy(PODLOVE)
        dote = copy.deepcopy(DOTE)
        for segment in podlove["transcripts"]:
            segment["speaker"] = "Existing"
            segment["voice"] = "Existing"
        for line in dote["lines"]:
            line["speakerDesignation"] = "Existing"
        transcript = make_transcript(audio, podlove=podlove, dote=dote, vtt=VTT, speakers=SPEAKERS)

        response = admin_client.post(
            reverse("cast-transcript:edit", args=(transcript.id,)),
            {
                "action": "review-known-speakers",
                "known_speaker_segment_1": "__blank__",
            },
        )

        assert response.status_code == 302
        transcript.refresh_from_db()
        assert transcript.podlove_data["transcripts"][1]["speaker"] == ""
        assert transcript.podlove_data["transcripts"][1]["voice"] == ""
        assert transcript.dote_data["lines"][1]["speakerDesignation"] == ""

    def test_review_action_without_changes_warns(self, admin_client, audio):
        speakers = {"segments": [{"index": 0, "start": 10.0, "speaker": None, "speaker_uncertain": True}]}
        transcript = make_transcript(audio, podlove=PODLOVE, dote=DOTE, speakers=speakers)

        response = admin_client.post(
            reverse("cast-transcript:edit", args=(transcript.id,)),
            {"action": "review-known-speakers"},
        )

        assert response.status_code == 302
        transcript.refresh_from_db()
        assert transcript.get_known_speaker_editor_decisions() == {}
        assert transcript.podlove_data["transcripts"][0]["speaker"] == ""

    def test_review_action_invalid_form_rerenders_with_error(self, admin_client, audio):
        transcript = make_transcript(audio, podlove=PODLOVE, dote=DOTE, speakers=SPEAKERS)

        response = admin_client.post(
            reverse("cast-transcript:edit", args=(transcript.id,)),
            {
                "action": "review-known-speakers",
                "known_speaker_segment_0": "not-a-choice",
            },
        )

        assert response.status_code == 200
        assert b"known-speaker segment decisions could not be saved" in response.content
        transcript.refresh_from_db()
        assert transcript.podlove_data["transcripts"][0]["speaker"] == ""

    def test_apply_action_without_suggestions_warns(self, admin_client, audio):
        transcript = make_transcript(audio, podlove=PODLOVE, dote=DOTE)
        response = admin_client.post(
            reverse("cast-transcript:edit", args=(transcript.id,)),
            {"action": "apply-known-speakers"},
        )
        assert response.status_code == 302
