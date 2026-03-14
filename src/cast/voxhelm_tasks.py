from __future__ import annotations

from django.shortcuts import get_object_or_404
from django_tasks import task

from .models import TranscriptGeneration
from .voxhelm import VoxhelmTranscriptService


@task(backend="cast_transcripts", enqueue_on_commit=False)
def complete_transcript_generation(generation_id: int) -> None:
    generation = get_object_or_404(
        TranscriptGeneration.objects.select_related("audio", "site"),
        pk=generation_id,
    )
    if generation.status == TranscriptGeneration.Status.SUCCEEDED:
        return

    generation.mark_running()
    service = VoxhelmTranscriptService(request_or_site=generation.site)
    try:
        service.complete_audio_job(
            generation.audio,
            job_id=generation.voxhelm_job_id,
            source_url=generation.source_url,
        )
    except Exception as exc:
        generation.mark_failed(str(exc))
        raise
    generation.mark_succeeded()
