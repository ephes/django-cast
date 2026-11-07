"""Bound reads of synthetic stored JSON before decoding or editorial writes."""

import json
from io import BytesIO

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse

from cast.models import Transcript
from cast.transcripts import parsing, services
from tests.known_speaker_apply_test import DOTE, PODLOVE, make_transcript


@pytest.mark.parametrize("chunk_size", [1, 8, 100])
def test_stored_json_ceiling_limits_even_short_or_growing_reads(monkeypatch, chunk_size):
    monkeypatch.setattr(parsing, "MAX_STORED_TRANSCRIPT_JSON_BYTES", 16, raising=False)

    class GrowingStream:
        consumed = 0

        def read(self, size=-1):
            assert 0 < size <= 17
            chunk = b" " * min(size, chunk_size)
            self.consumed += len(chunk)
            return chunk

    stream = GrowingStream()
    with pytest.raises(parsing.TranscriptArtifactError, match="exceeds"):
        parsing.load_json_artifact(stream)
    assert stream.consumed == 17


def test_stored_json_accepts_exact_byte_limit(monkeypatch):
    raw = '{"text":"é"}'.encode()
    monkeypatch.setattr(parsing, "MAX_STORED_TRANSCRIPT_JSON_BYTES", len(raw), raising=False)
    assert parsing.load_json_artifact(BytesIO(raw)) == {"text": "é"}


@pytest.mark.django_db
@pytest.mark.parametrize("operation", ["get", "post"])
def test_oversized_stored_json_refuses_editor_without_mutation(admin_client, audio, monkeypatch, operation):
    transcript = make_transcript(audio, podlove=PODLOVE)
    raw = b'{"padding":"' + b"x" * 2048 + b'"}'
    transcript.podlove.save("large.json", ContentFile(raw))
    monkeypatch.setattr(parsing, "MAX_STORED_TRANSCRIPT_JSON_BYTES", 1024, raising=False)
    before = Transcript.objects.filter(pk=transcript.pk).values().get()
    name = transcript.podlove.name
    url = reverse("cast-transcript:edit", args=(transcript.pk,))
    if operation == "get":
        response = admin_client.get(url)
    else:
        response = admin_client.post(
            url, {"action": "glossary-refresh", "artifact_revision": services.artifact_revision(transcript)}
        )
    assert response.status_code == 400
    assert b"Invalid transcript JSON" in response.content
    assert Transcript.objects.filter(pk=transcript.pk).values().get() == before
    with transcript.podlove.storage.open(name, "rb") as file:
        assert file.read() == raw
    assert transcript._load_transcript_json("podlove") == {}


@pytest.mark.django_db
@pytest.mark.parametrize("field", ["podlove", "dote", "speakers", "corrections"])
def test_public_properties_refuse_oversized_json(audio, monkeypatch, field):
    transcript = make_transcript(audio)
    getattr(transcript, field).save("large.json", ContentFile(b'{"padding":"' + b"x" * 2048 + b'"}'))
    monkeypatch.setattr(parsing, "MAX_STORED_TRANSCRIPT_JSON_BYTES", 1024, raising=False)
    assert getattr(transcript, f"{field}_data") == {}


@pytest.mark.django_db
@pytest.mark.parametrize("endpoint", ["podlove", "podcastindex"])
def test_public_json_endpoint_rejects_oversized_stored_json(client, episode, monkeypatch, endpoint):
    transcript = make_transcript(episode.podcast_audio)
    field = "podlove" if endpoint == "podlove" else "dote"
    data = (
        PODLOVE if field == "podlove" else {"lines": [{**line, "endTime": "00:00:20,000"} for line in DOTE["lines"]]}
    )
    getattr(transcript, field).save("large.json", ContentFile(json.dumps({**data, "padding": "x" * 2048}).encode()))
    monkeypatch.setattr(parsing, "MAX_STORED_TRANSCRIPT_JSON_BYTES", 1024, raising=False)
    response = client.get(reverse(f"cast:{endpoint}-transcript-json", kwargs={"pk": transcript.pk}))
    assert response.status_code == 400
    assert b"Invalid JSON format" in response.content


@pytest.mark.django_db
@pytest.mark.parametrize("reader", ["player", "serializer"])
def test_player_and_serializer_refuse_oversized_json(audio, monkeypatch, reader):
    from cast.api.serializers import AudioPodloveSerializer
    from cast.player import _load_sanitized_segments

    transcript = make_transcript(audio, podlove=PODLOVE)
    transcript.podlove.save("large.json", ContentFile(json.dumps({**PODLOVE, "padding": "x" * 2048}).encode()))
    monkeypatch.setattr(parsing, "MAX_STORED_TRANSCRIPT_JSON_BYTES", 1024, raising=False)
    if reader == "player":
        assert _load_sanitized_segments(audio, episode=None) == []
    else:
        assert AudioPodloveSerializer()._load_podlove_data(audio) == {}


def test_stored_json_keeps_utf8_encoding_policy():
    with pytest.raises(parsing.TranscriptArtifactError):
        parsing.load_json_artifact(BytesIO('{"text":"hello"}'.encode("utf-16")))
