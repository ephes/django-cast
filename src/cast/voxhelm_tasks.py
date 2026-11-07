from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from django_tasks import task

from .models import Episode, TranscriptGeneration
from .voxhelm import VoxhelmTranscriptService
from .voxhelm.service import StaleTranscriptAttempt


@task(backend="cast_transcripts")
def complete_transcript_generation(
    generation_id: int, episode_id: int | None = None, *, attempt_id: str | None = None, using: str = "default"
) -> None:
    """Complete only the immutable attempt handed off by the committed producer."""
    # Old queued tasks cannot prove ownership. A stale generation can be retried.
    if attempt_id is None:
        return
    current = TranscriptGeneration.objects.using(using).filter(pk=generation_id, attempt_id=attempt_id)
    with transaction.atomic(using=using):
        if not current.filter(status=TranscriptGeneration.Status.QUEUED).update(
            status=TranscriptGeneration.Status.RUNNING,
            error_message="",
            started_at=timezone.now(),
            completed_at=None,
            updated_at=timezone.now(),
        ):
            return
        generation = current.select_related("audio", "site").get()
    try:
        service = VoxhelmTranscriptService(request_or_site=generation.site)
        service.complete_audio_job(
            generation.audio,
            job_id=generation.voxhelm_job_id,
            source_url=generation.source_url,
            episode=Episode.objects.using(using).filter(pk=episode_id).first(),
            generation_id=generation_id,
            attempt_id=attempt_id,
            using=using,
        )
    except StaleTranscriptAttempt:
        return
    except Exception as exc:
        changed = current.filter(status=TranscriptGeneration.Status.RUNNING).update(
            status=TranscriptGeneration.Status.FAILED,
            error_message=str(exc),
            completed_at=timezone.now(),
            updated_at=timezone.now(),
        )
        if changed:
            raise
        return
    current.filter(status=TranscriptGeneration.Status.RUNNING).update(
        status=TranscriptGeneration.Status.SUCCEEDED,
        error_message="",
        completed_at=timezone.now(),
        updated_at=timezone.now(),
    )
