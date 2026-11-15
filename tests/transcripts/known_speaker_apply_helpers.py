"""Shared test data and setup helpers."""

import json

from django.core.files.base import ContentFile

from cast.models import Transcript


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
