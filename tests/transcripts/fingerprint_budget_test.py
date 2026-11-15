"""Bound candidate evidence hashing with synthetic storage streams."""

import hashlib
from contextlib import nullcontext
from io import BytesIO

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse

from cast.models import Transcript
from cast.transcripts import parsing
from tests.known_speaker_apply_test import make_transcript
from tests.voice_reference_candidate_picker_test import podlove_segment


@pytest.mark.parametrize("kind", ["oversized", "endless", "short"])
def test_fingerprint_stops_at_artifact_limit(monkeypatch, kind):
    monkeypatch.setattr(parsing, "MAX_TRANSCRIPT_FINGERPRINT_ARTIFACT_BYTES", 16, raising=False)
    transcript = Transcript(collection_id=1, podlove="synthetic.json")

    class Reader:
        consumed = 0
        source = BytesIO(b"x" * 17)

        def read(self, size):
            assert 0 < size <= 17
            if kind == "endless":
                result = b"x" * size
            else:
                result = self.source.read(min(size, 1 if kind == "short" else size))
            self.consumed += len(result)
            return result

    reader = Reader()
    monkeypatch.setattr(transcript.podlove.storage, "open", lambda *args: nullcontext(reader))
    with pytest.raises(parsing.TranscriptArtifactError, match="fingerprint.*budget"):
        transcript.transcript_artifact_fingerprint(enforce_byte_budget=True)
    assert reader.consumed == 17


def test_fingerprint_accepts_exact_limits_and_preserves_hash(monkeypatch):
    monkeypatch.setattr(parsing, "MAX_TRANSCRIPT_FINGERPRINT_ARTIFACT_BYTES", 4, raising=False)
    monkeypatch.setattr(parsing, "MAX_TRANSCRIPT_FINGERPRINT_TOTAL_BYTES", 8, raising=False)
    transcript = Transcript(collection_id=1, podlove="p.json", dote="d.json")
    monkeypatch.setattr(transcript.podlove.storage, "open", lambda *args: BytesIO(b"test"))
    assert (
        transcript.transcript_artifact_fingerprint(enforce_byte_budget=True)
        == hashlib.sha256(b"podlove\0test\0dote\0test\0").hexdigest()
    )


def test_fingerprint_stops_at_aggregate_limit(monkeypatch):
    monkeypatch.setattr(parsing, "MAX_TRANSCRIPT_FINGERPRINT_ARTIFACT_BYTES", 16, raising=False)
    monkeypatch.setattr(parsing, "MAX_TRANSCRIPT_FINGERPRINT_TOTAL_BYTES", 6, raising=False)
    transcript = Transcript(collection_id=1, podlove="p.json", dote="d.json")
    streams = []

    def opened(*args):
        stream = BytesIO(b"test")
        streams.append(stream)
        return nullcontext(stream)

    monkeypatch.setattr(transcript.podlove.storage, "open", opened)
    with pytest.raises(parsing.TranscriptArtifactError, match="fingerprint.*budget"):
        transcript.transcript_artifact_fingerprint(enforce_byte_budget=True)
    assert sum(stream.tell() for stream in streams) == 7


@pytest.mark.django_db
def test_editor_refuses_oversized_vtt_before_signing(admin_client, audio, monkeypatch, mocker):
    transcript = make_transcript(audio, podlove={"transcripts": [podlove_segment("Synthetic", "1", "12")]})
    transcript.vtt.save("large.vtt", ContentFile(b"x" * 2048))
    monkeypatch.setattr(parsing, "MAX_TRANSCRIPT_FINGERPRINT_ARTIFACT_BYTES", 1024, raising=False)
    sign = mocker.patch("cast.transcripts.editing.sign_voice_reference_candidate")
    response = admin_client.get(reverse("cast-transcript:edit", args=(transcript.pk,)))
    assert response.status_code == 400
    assert b"Replace" in response.content
    sign.assert_not_called()


@pytest.mark.django_db
def test_storage_paths_hash_complete_artifacts_beyond_the_editor_budget(audio, monkeypatch):
    """save() and the public mapping fingerprint never apply the editor budget."""
    monkeypatch.setattr(parsing, "MAX_TRANSCRIPT_FINGERPRINT_ARTIFACT_BYTES", 1024, raising=False)
    monkeypatch.setattr(parsing, "MAX_TRANSCRIPT_FINGERPRINT_TOTAL_BYTES", 1024, raising=False)
    transcript = make_transcript(audio, podlove={"transcripts": [podlove_segment("Synthetic", "1", "12")]})
    transcript.vtt.save("large.vtt", ContentFile(b"WEBVTT\n\n" + b"x" * 2048))
    transcript.refresh_from_db()
    assert transcript.source_fingerprint == transcript.transcript_artifact_fingerprint()
    Transcript.objects.filter(pk=transcript.pk).update(source_fingerprint="")
    transcript.refresh_from_db()
    assert transcript.mapping_fingerprint() == transcript.transcript_artifact_fingerprint()
    with pytest.raises(parsing.TranscriptArtifactError, match="fingerprint.*budget"):
        transcript.transcript_artifact_fingerprint(enforce_byte_budget=True)
