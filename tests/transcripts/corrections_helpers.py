"""Shared test data and setup helpers."""

import json

from django.core.files.base import ContentFile

from cast.models import (
    Transcript,
)
from cast.transcripts import dote, webvtt

TEXTS = [
    (10000, "John said Gunacorn is fast."),
    (12500, "We use Button Down for mail."),
    (15000, "Nothing to fix here."),
    (17500, "John's talk & more."),
]


def podlove_data(texts=TEXTS, speaker=""):
    return {
        "version": 1,
        "transcripts": [
            {"start_ms": start_ms, "speaker": speaker, "voice": speaker, "text": text} for start_ms, text in texts
        ],
    }


def dote_data(texts=TEXTS):
    def stamp(ms):
        return f"00:00:{ms // 1000:02},{ms % 1000:03}"

    return {
        "lines": [
            {"startTime": stamp(ms), "endTime": stamp(ms + 1000), "speakerDesignation": "", "text": text}
            for ms, text in texts
        ]
    }


def vtt_content(texts=TEXTS):
    cues = []
    for ms, text in texts:
        escaped = webvtt.escape_cue_text(text)
        cues.append(f"00:00:{ms // 1000:02}.{ms % 1000:03} --> 00:00:{ms // 1000 + 1:02}.{ms % 1000:03}\n{escaped}\n")
    return "WEBVTT\n\n" + "\n".join(cues)


def make_transcript(audio, *, texts=TEXTS, vtt=None, speakers=None, speaker=""):
    transcript = Transcript.objects.create(audio=audio)
    podlove_content = json.dumps(podlove_data(texts, speaker)).encode()
    transcript.podlove.save("t.podlove.json", ContentFile(podlove_content), save=False)
    transcript.dote.save("t.dote.json", ContentFile(json.dumps(dote_data(texts)).encode()), save=False)
    transcript.vtt.save("t.vtt", ContentFile((vtt if vtt is not None else vtt_content(texts)).encode()), save=False)
    if speakers is not None:
        transcript.speakers.save("t.speakers.json", ContentFile(json.dumps(speakers).encode()), save=False)
    transcript.save()
    return transcript


def public_texts(transcript):
    transcript.refresh_from_db()
    podlove_texts = {segment["start_ms"]: segment["text"] for segment in transcript.podlove_data["transcripts"]}
    dote_texts = {dote.dote_timestamp_to_ms(line["startTime"]): line["text"] for line in transcript.dote_data["lines"]}
    return podlove_texts, dote_texts, transcript._load_text_file("vtt")


BODY = json.dumps(
    [
        {
            "type": "overview",
            "value": [
                {"type": "paragraph", "value": '<p>Newsletter: <a href="https://example.com">Buttondown</a></p>'},
            ],
        }
    ]
)
