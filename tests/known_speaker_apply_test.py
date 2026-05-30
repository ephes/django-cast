"""Tests for reviewing and applying known-speaker suggestions to public output."""

import json

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse

from cast.models import Transcript
from cast.models.transcript import _dote_timestamp_to_ms, _webvtt_timestamp_to_ms


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
class TestKnownSpeakerReviewView:
    def test_edit_page_shows_review_panel(self, admin_client, audio):
        transcript = make_transcript(audio, podlove=PODLOVE, dote=DOTE, speakers=SPEAKERS)
        response = admin_client.get(reverse("cast-transcript:edit", args=(transcript.id,)))
        assert response.status_code == 200
        assert b"Known-speaker suggestions" in response.content

    def test_apply_action_labels_public_output(self, admin_client, audio):
        transcript = make_transcript(audio, podlove=PODLOVE, dote=DOTE, speakers=SPEAKERS)
        response = admin_client.post(
            reverse("cast-transcript:edit", args=(transcript.id,)),
            {"action": "apply-known-speakers"},
        )
        assert response.status_code == 302
        transcript.refresh_from_db()
        assert transcript.podlove_data["transcripts"][0]["speaker"] == "Johannes"

    def test_apply_action_without_suggestions_warns(self, admin_client, audio):
        transcript = make_transcript(audio, podlove=PODLOVE, dote=DOTE)
        response = admin_client.post(
            reverse("cast-transcript:edit", args=(transcript.id,)),
            {"action": "apply-known-speakers"},
        )
        assert response.status_code == 302
