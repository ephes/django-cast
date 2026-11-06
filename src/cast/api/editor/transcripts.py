"""Editor API transcript generation for podcast episodes."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ImproperlyConfigured, ObjectDoesNotExist
from django.urls import reverse
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from wagtail.models import Site

from ...models import Audio, Episode, Transcript, TranscriptGeneration
from ...transcript_sanitization import (
    editor_speaker_preview_episode,
    public_speaker_mapping_for_transcript,
    strict_public_speaker_labels_for_transcript,
)
from ...transcripts.editing import episode_from_latest_revision
from ...transcripts.generation_status import get_transcript_generation, transcript_complete
from ...voxhelm import (
    VoxhelmError,
    build_known_speaker_references,
    count_episode_diarization_speakers,
    enqueue_audio_transcript_generation,
    resolve_bool_setting,
    voxhelm_configured,
)
from .errors import EditorFlatError, EditorPermissionDenied, EditorValidationError
from .media import audio_permission_policy
from .views import EditorAPIView, EpisodeEditorMixin


def _bool_setting_payload(name: str, site: Site | None) -> dict[str, Any]:
    try:
        enabled, source = resolve_bool_setting(name, False, request_or_site=site)
    except ImproperlyConfigured as exc:
        return {"enabled": None, "source": "invalid", "error": str(exc)}
    return {"enabled": enabled, "source": source}


def configuration_payload(*, draft: Episode, audio: Audio | None, site: Site | None) -> dict[str, Any]:
    """Describe what a generation requested now would send to Voxhelm.

    ``source`` names the level each boolean came from (``site``, ``django``,
    ``environment``, ``default``, or ``invalid``), so a client can tell when a
    Wagtail site setting overrides the deployment environment.
    """
    diarization = _bool_setting_payload("CAST_VOXHELM_DIARIZATION_ENABLED", site)
    known_speaker = _bool_setting_payload("CAST_VOXHELM_KNOWN_SPEAKER_ENABLED", site)
    mode = audio.transcript_diarization_mode if audio is not None else None
    if mode == Audio.TranscriptDiarizationMode.ENABLED:
        diarize = True
    elif mode == Audio.TranscriptDiarizationMode.DISABLED:
        diarize = False
    else:
        diarize = diarization["enabled"] is True
    request_known_speakers = diarize and known_speaker["enabled"] is True
    return {
        "voxhelm_configured": voxhelm_configured(request_or_site=site),
        "diarization": diarization,
        "known_speaker": known_speaker,
        "transcript_diarization_mode": mode,
        "diarize": diarize,
        "expected_speaker_count": count_episode_diarization_speakers(draft) if diarize else None,
        "known_speaker_count": len(build_known_speaker_references(draft)) if request_known_speakers else 0,
    }


def generation_payload(generation: TranscriptGeneration | None) -> dict[str, Any] | None:
    if generation is None:
        return None
    return {
        "status": "interrupted" if generation.is_stale else generation.status,
        "active": generation.is_active and not generation.is_stale,
        "error": generation.error_message,
        "task_ref": generation.task_ref,
        "voxhelm_job_id": generation.voxhelm_job_id,
        "created_at": generation.created_at,
        "updated_at": generation.updated_at,
        "started_at": generation.started_at,
        "completed_at": generation.completed_at,
    }


def _speaker_context_episode(episode: Episode, user: Any) -> Episode | None:
    preview = editor_speaker_preview_episode(episode, user)
    if preview is not None:
        return preview
    return episode if episode.live else None


def transcript_payload(transcript: Transcript | None, *, episode: Episode, user: Any) -> dict[str, Any] | None:
    if transcript is None:
        return None
    speaker_labels = transcript.get_speaker_labels()
    context_episode = _speaker_context_episode(episode, user)
    mapping = public_speaker_mapping_for_transcript(transcript, episode=context_episode)
    allowed = strict_public_speaker_labels_for_transcript(transcript, episode=context_episode)
    preview_labels: list[str] = []
    for label in speaker_labels:
        shown = mapping.get(label, label)
        if shown in allowed and shown not in preview_labels:
            preview_labels.append(shown)
    suggestions = None
    if transcript.speakers:
        summary = transcript.known_speaker_review_summary()
        suggestions = {key: summary[key] for key in ("total", "confident", "uncertain", "by_speaker")}
    mappings = [
        {
            "speaker_label": mapping_row.speaker_label,
            "review_state": mapping_row.review_state,
            "contributor": (
                {"id": mapping_row.contributor_id, "slug": mapping_row.contributor.slug}
                if mapping_row.contributor is not None
                else None
            ),
            "display_name": mapping_row.target_display_name,
        }
        for mapping_row in transcript.speaker_mappings.select_related("contributor").filter(active=True)
    ]
    return {
        "id": transcript.pk,
        "complete": transcript_complete(transcript),
        "edit_url": reverse("cast-transcript:edit", args=(transcript.pk,)),
        "speaker_labels": speaker_labels,
        "preview_speaker_labels": preview_labels,
        "speaker_mappings": mappings,
        "known_speaker_suggestions": suggestions,
    }


def _transcript_or_none(audio: Audio | None) -> Transcript | None:
    if audio is None:
        return None
    try:
        return audio.transcript
    except ObjectDoesNotExist:
        return None


class EpisodeTranscriptView(EpisodeEditorMixin, EditorAPIView):
    """Read or request Voxhelm transcript generation for an episode's podcast audio."""

    required_scopes = {"GET": None, "POST": "write"}

    def _target(self, request: Request, pk: int, *, denied_message: str) -> tuple[Episode, Episode, Any, Site | None]:
        episode = self._get_episode(pk, request.user, denied_message=denied_message)
        # The latest revision carries the draft's podcast audio and contributor assignments,
        # matching the Wagtail "Generate transcript" action.
        draft = episode_from_latest_revision(episode)
        site = episode.get_site() or Site.find_for_request(request._request)
        return episode, draft, draft.podcast_audio, site

    def _payload(
        self,
        request: Request,
        *,
        episode: Episode,
        draft: Episode,
        audio: Any,
        site: Any,
        generation: TranscriptGeneration | None,
    ) -> dict:
        return {
            "episode": {"id": episode.pk},
            "audio": {"id": audio.pk} if audio is not None else None,
            "configuration": configuration_payload(draft=draft, audio=audio, site=site),
            "generation": generation_payload(generation),
            "transcript": transcript_payload(_transcript_or_none(audio), episode=episode, user=request.user),
        }

    def get(self, request: Request, *args: Any, pk: int, **kwargs: Any) -> Response:
        episode, draft, audio, site = self._target(request, pk, denied_message="You cannot view this draft.")
        generation = get_transcript_generation(audio) if audio is not None else None
        return Response(
            self._payload(request, episode=episode, draft=draft, audio=audio, site=site, generation=generation)
        )

    def post(self, request: Request, *args: Any, pk: int, **kwargs: Any) -> Response:
        user = request.user
        episode, draft, audio, site = self._target(request, pk, denied_message="You cannot edit this draft.")
        if audio is None:
            raise EditorValidationError(
                {
                    "podcast_audio": [
                        {"code": "required", "message": "Set podcast_audio before generating a transcript."}
                    ]
                }
            )
        if not audio_permission_policy.user_has_permission_for_instance(user, "change", audio):
            raise EditorPermissionDenied("You cannot generate a transcript for this episode's audio.")
        try:
            result = enqueue_audio_transcript_generation(
                audio=audio, request_or_site=site, requested_by=user, episode=draft
            )
        except ImproperlyConfigured as exc:
            raise EditorFlatError(
                "voxhelm_not_configured",
                f"Transcript generation is not configured: {exc}",
                status_code=status.HTTP_409_CONFLICT,
            ) from exc
        except VoxhelmError as exc:
            raise EditorFlatError(
                "voxhelm_error",
                f"Transcript generation failed: {exc}",
                status_code=status.HTTP_502_BAD_GATEWAY,
            ) from exc
        data = {
            "enqueued": result.enqueued,
            **self._payload(
                request, episode=episode, draft=draft, audio=audio, site=site, generation=result.generation
            ),
        }
        return Response(data, status=status.HTTP_202_ACCEPTED)
