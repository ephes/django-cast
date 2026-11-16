"""Bind destructive admin consent to the reviewed transcript and audio generation."""

from __future__ import annotations

import hashlib
import json

from django.core import signing

from cast.models import Audio, Transcript, TranscriptGeneration

from .editing import transcript_evidence

SALT = "cast.transcript-regeneration"


class StaleRegenerationConfirmation(ValueError):
    """The editor must review a fresh replacement confirmation."""


def regeneration_revision(audio: Audio, transcript: Transcript) -> str:
    mappings = [
        {
            "id": mapping.pk,
            "speaker": mapping.speaker_label,
            "contributor": mapping.contributor_id,
            "name": mapping.target_display_name,
            "active": mapping.active,
            "state": mapping.review_state,
            "source": mapping.source_artifact_fingerprint,
            "reviewed_at": str(mapping.reviewed_at),
        }
        for mapping in transcript.speaker_mappings.select_related("contributor").order_by("pk")
    ]
    generation = TranscriptGeneration.objects.using(audio._state.db).filter(audio_id=audio.pk).first()
    evidence = {
        "database": audio._state.db,
        **transcript_evidence(transcript),
        "mappings": mappings,
        "attempt": [generation.pk, str(generation.attempt_id)] if generation else None,
    }
    return hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()


def sign_regeneration(audio: Audio, transcript: Transcript) -> str:
    return signing.dumps(regeneration_revision(audio, transcript), salt=SALT)


def check_regeneration(audio: Audio, transcript: Transcript | None, token: str) -> None:
    # An initially transcript-free POST also rechecks under the audio lock.
    if transcript is None and not token:
        return
    try:
        revision = signing.loads(token, salt=SALT)
    except signing.BadSignature:
        revision = None
    if transcript is None or revision != regeneration_revision(audio, transcript):
        raise StaleRegenerationConfirmation("Reload and confirm replacement of the current transcript first.")
