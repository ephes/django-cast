"""Transcript generation status helpers with leaf-model imports only.

This module is imported during ``cast.models`` package initialisation (via
``models/pages`` → ``wagtail_panels``), so it must only import model LEAF
submodules, never the ``cast.models`` package or ``cast.voxhelm``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.urls import reverse

from cast.models.transcript_generation import TranscriptGeneration

if TYPE_CHECKING:
    from cast.models.audio import Audio
    from cast.models.transcript import Transcript


def transcript_complete(transcript: Transcript) -> bool:
    if not (transcript.podlove and transcript.vtt and transcript.dote):
        return False
    podlove_transcripts = transcript.podlove_data.get("transcripts")
    dote_lines = transcript.dote_data.get("lines")
    return bool(podlove_transcripts) and bool(dote_lines)


def get_transcript_generation(audio: Audio) -> TranscriptGeneration | None:
    try:
        return audio.transcript_generation
    except TranscriptGeneration.DoesNotExist:
        return None


def get_transcript_generation_status_context(*, audio: Audio) -> dict[str, str | bool]:
    generation = get_transcript_generation(audio)
    if generation is None:
        return {
            "transcript_generation_active": False,
            "transcript_generation_status": "",
            "transcript_generation_message": "",
            "transcript_generation_error": "",
            "transcript_generation_transcript_url": "",
        }

    message_lookup = {
        TranscriptGeneration.Status.QUEUED.value: "Transcript generation is queued.",
        TranscriptGeneration.Status.RUNNING.value: "Transcript generation is running.",
        TranscriptGeneration.Status.SUCCEEDED.value: "Transcript generation completed.",
        TranscriptGeneration.Status.FAILED.value: "Transcript generation failed.",
    }
    transcript_url = ""
    if generation.status == TranscriptGeneration.Status.SUCCEEDED and hasattr(audio, "transcript"):
        transcript_url = reverse("cast-transcript:edit", args=(audio.transcript.pk,))
    return {
        "transcript_generation_active": generation.is_active,
        "transcript_generation_status": generation.get_status_display(),
        "transcript_generation_message": message_lookup[generation.status],
        "transcript_generation_error": generation.error_message,
        "transcript_generation_transcript_url": transcript_url,
    }
