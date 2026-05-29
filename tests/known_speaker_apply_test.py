"""Tests for reviewing and applying known-speaker suggestions to public output."""

import json

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse

from cast.models import Transcript
from cast.models.transcript import _dote_timestamp_to_ms


def make_transcript(audio, *, podlove=None, dote=None, speakers=None):
    transcript = Transcript.objects.create(audio=audio)
    if podlove is not None:
        transcript.podlove.save("t.podlove.json", ContentFile(json.dumps(podlove).encode()), save=False)
    if dote is not None:
        transcript.dote.save("t.dote.json", ContentFile(json.dumps(dote).encode()), save=False)
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
def test_apply_labels_confident_segments_only(audio):
    transcript = make_transcript(audio, podlove=PODLOVE, dote=DOTE, speakers=SPEAKERS)

    applied = transcript.apply_known_speaker_suggestions()

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
