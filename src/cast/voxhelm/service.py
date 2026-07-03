from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.http import HttpRequest
from wagtail.models import Site

from cast.models.contributors import ContributorVoiceReference
from cast.models.transcript import Transcript
from cast.models.transcript_generation import TranscriptGeneration
from cast.transcripts.generation_status import get_transcript_generation

from ..file_replacement import StagedFileReplacementGroup, stage_file_replacement
from .client import TERMINAL_JOB_STATES, VoxhelmClient
from .exceptions import VoxhelmError
from .task_refs import resolve_audio_task_ref

if TYPE_CHECKING:
    from cast.models.audio import Audio

DOTE_REQUIRED_KEYS = {"startTime", "endTime", "speakerDesignation", "text"}


@dataclass(frozen=True)
class TranscriptGenerationResult:
    transcript: Transcript
    created: bool
    job_id: str
    source_url: str


@dataclass(frozen=True)
class TranscriptSubmission:
    job_id: str
    source_url: str
    task_ref: str
    job_payload: dict[str, Any]


@dataclass(frozen=True)
class TranscriptEnqueueResult:
    generation: TranscriptGeneration
    enqueued: bool


def resolve_audio_source_url(audio: Audio) -> str:
    for _audio_format, field in audio.uploaded_audio_files:
        url = getattr(field, "url", "")
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            return url
    audio_id = audio.pk if audio.pk is not None else "unsaved"
    raise VoxhelmError(f"Audio {audio_id} does not expose an absolute HTTP(S) source URL.")


def require_artifact_path(job_payload: dict[str, Any], format_name: str) -> str:
    result = job_payload.get("result")
    if not isinstance(result, dict):
        raise VoxhelmError("Voxhelm job did not include a result payload.")
    artifacts = result.get("artifacts")
    if not isinstance(artifacts, dict):
        raise VoxhelmError("Voxhelm job did not include artifact references.")
    artifact_path = artifacts.get(format_name)
    if not isinstance(artifact_path, str) or not artifact_path:
        raise VoxhelmError(f"Voxhelm job did not expose a '{format_name}' artifact.")
    return artifact_path


def optional_artifact_path(job_payload: dict[str, Any], format_name: str) -> str | None:
    result = job_payload.get("result")
    if not isinstance(result, dict):
        return None
    artifacts = result.get("artifacts")
    if not isinstance(artifacts, dict):
        return None
    artifact_path = artifacts.get(format_name)
    if isinstance(artifact_path, str) and artifact_path:
        return artifact_path
    return None


def parse_json_artifact(content: bytes, *, format_name: str) -> dict[str, Any]:
    try:
        data = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VoxhelmError(f"Voxhelm {format_name} artifact was not valid UTF-8 JSON.") from exc
    if not isinstance(data, dict):
        raise VoxhelmError(f"Voxhelm {format_name} artifact must be a JSON object.")
    return data


def validate_json_list_artifact(content: bytes, *, format_name: str, list_key: str) -> list[Any]:
    data = parse_json_artifact(content, format_name=format_name)
    items = data.get(list_key)
    if not isinstance(items, list):
        raise VoxhelmError(f"Voxhelm {format_name} artifact must include a '{list_key}' list.")
    return items


def validate_podlove_artifact(content: bytes) -> None:
    validate_json_list_artifact(content, format_name="podlove", list_key="transcripts")


def validate_dote_artifact(content: bytes) -> None:
    lines = validate_json_list_artifact(content, format_name="dote", list_key="lines")
    for line in lines:
        if not isinstance(line, dict):
            raise VoxhelmError("Voxhelm dote artifact lines must be JSON objects.")
        missing_keys = DOTE_REQUIRED_KEYS.difference(line.keys())
        if missing_keys:
            missing_display = ", ".join(sorted(missing_keys))
            raise VoxhelmError(f"Voxhelm dote artifact lines must include keys: {missing_display}.")


def validate_vtt_artifact(content: bytes) -> None:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise VoxhelmError("Voxhelm vtt artifact was not valid UTF-8 text.") from exc
    if not text.startswith("WEBVTT"):
        raise VoxhelmError("Voxhelm vtt artifact must start with the WEBVTT header.")


def validate_transcript_artifacts(*, podlove: bytes, dote: bytes, vtt: bytes, speakers: bytes | None = None) -> None:
    validate_podlove_artifact(podlove)
    validate_dote_artifact(dote)
    validate_vtt_artifact(vtt)
    if speakers is not None:
        parse_json_artifact(speakers, format_name="speakers")


def build_failure_message(job_payload: dict[str, Any]) -> str:
    error = job_payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    job_id = job_payload.get("id", "<unknown>")
    state = job_payload.get("state", "<unknown>")
    return f"Voxhelm job {job_id} ended in state '{state}'."


def replace_file(field, filename: str, content: bytes) -> None:
    stage_file_replacement(field, filename, content)


def count_episode_diarization_speakers(episode: Any) -> int | None:
    assignments = getattr(episode, "contributor_assignments", None)
    if assignments is None:
        return None
    if hasattr(assignments, "all"):
        assignments = assignments.all()

    contributor_ids = set()
    for assignment in assignments:
        contributor_id = getattr(assignment, "contributor_id", None)
        if contributor_id is not None:
            contributor_ids.add(contributor_id)
    if len(contributor_ids) < 2:
        return None
    return len(contributor_ids)


def resolve_diarization_speaker_count(audio: Audio, *, episode: Any | None = None) -> int | None:
    if episode is not None:
        return count_episode_diarization_speakers(episode)
    episode_manager = getattr(audio, "episodes", None)
    if episode_manager is None:
        return None

    episodes = list(episode_manager.all())
    if len(episodes) != 1:
        return None
    return count_episode_diarization_speakers(episodes[0])


def build_known_speaker_references(episode: Any) -> list[dict[str, Any]]:
    """Build the Voxhelm known-speaker reference payload for an episode.

    Only approved, usable references for the episode's expected contributors are
    included. Hidden contributors are excluded unless a reference explicitly
    opted into hidden-contributor use. Source ranges resolve to absolute audio
    URLs. Uploaded clips are included only when their protected storage backend
    provides an absolute URL, for example a short-lived signed URL; no-URL
    private clips are skipped.
    """
    if episode is None:
        return []
    assignments = getattr(episode, "contributor_assignments", None)
    if assignments is None:
        return []
    if hasattr(assignments, "all"):
        assignments = assignments.all()

    ordered_contributors: dict[Any, Any] = {}
    for assignment in assignments:
        contributor_id = getattr(assignment, "contributor_id", None)
        contributor = getattr(assignment, "contributor", None)
        if contributor_id is not None and contributor is not None and contributor_id not in ordered_contributors:
            ordered_contributors[contributor_id] = contributor
    if not ordered_contributors:
        return []

    references = (
        ContributorVoiceReference.objects.usable_known_speaker()
        .filter(contributor_id__in=list(ordered_contributors))
        .select_related("source_audio")
        .order_by("contributor_id", "sort_order", "id")
    )
    grouped: dict[Any, list[dict[str, Any]]] = {}
    for reference in references:
        entry = build_known_speaker_reference_entry(reference)
        if entry is not None:
            grouped.setdefault(reference.contributor_id, []).append(entry)

    known_speakers: list[dict[str, Any]] = []
    for contributor_id, contributor in ordered_contributors.items():
        entries = grouped.get(contributor_id)
        if entries:
            known_speakers.append({"id": str(contributor_id), "name": contributor.display_name, "references": entries})
    return known_speakers


def build_known_speaker_reference_entry(reference: Any) -> dict[str, Any] | None:
    if reference.is_source_range and reference.source_audio_id is not None:
        try:
            url = resolve_audio_source_url(reference.source_audio)
        except VoxhelmError:
            return None
        return {
            "kind": "source_range",
            "audio": {"kind": "url", "url": url},
            "start": float(reference.start_seconds),
            "end": float(reference.end_seconds),
        }
    if reference.clip:
        try:
            url = reference.clip.url
        except ValueError:
            return None
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            return {"kind": "clip_artifact", "audio": {"kind": "url", "url": url}}
    return None


def client_known_speaker_enabled(client: object) -> bool:
    return getattr(client, "known_speaker_enabled", False) is True


def client_diarization_enabled(client: object) -> bool:
    # Strict ``is True`` keeps duck-typed test clients and mocks without a real bool on the non-diarized path.
    return getattr(client, "diarization_enabled", False) is True


def resolve_audio_diarization_enabled(audio: Audio, client: object) -> bool:
    mode = getattr(audio, "transcript_diarization_mode", "inherit")
    if mode == "enabled":
        return True
    if mode == "disabled":
        return False
    return client_diarization_enabled(client)


class VoxhelmTranscriptService:
    def __init__(
        self,
        *,
        client: VoxhelmClient | None = None,
        request_or_site: HttpRequest | Site | None = None,
    ) -> None:
        self.client = client or VoxhelmClient.from_settings(request_or_site=request_or_site)

    def submit_for_audio(
        self,
        audio: Audio,
        *,
        task_ref: str | None = None,
        episode: Any | None = None,
    ) -> TranscriptSubmission:
        if audio.pk is None:
            raise VoxhelmError("Audio must be saved before requesting a transcript.")

        source_url = resolve_audio_source_url(audio)
        diarization_enabled = resolve_audio_diarization_enabled(audio, self.client)
        speaker_count = resolve_diarization_speaker_count(audio, episode=episode) if diarization_enabled else None
        resolved_task_ref = resolve_audio_task_ref(
            audio.pk,
            task_ref=task_ref,
            diarization_enabled=diarization_enabled,
            diarization_speaker_count=speaker_count,
        )
        known_speakers: list[dict[str, Any]] = []
        if diarization_enabled and client_known_speaker_enabled(self.client) and episode is not None:
            known_speakers = build_known_speaker_references(episode)
        extra_job_kwargs: dict[str, Any] = {}
        if known_speakers:
            extra_job_kwargs["known_speakers"] = known_speakers
        job_payload = self.client.submit_transcription_job(
            source_url=source_url,
            task_ref=resolved_task_ref,
            context={"consumer": "django-cast", "audio_id": audio.pk},
            speaker_count=speaker_count,
            diarization_enabled=diarization_enabled,
            **extra_job_kwargs,
        )
        state = str(job_payload.get("state", ""))
        if state in TERMINAL_JOB_STATES and state != "succeeded":
            raise VoxhelmError(build_failure_message(job_payload))
        job_id = str(job_payload.get("id", "")).strip()
        if not job_id:
            raise VoxhelmError("Voxhelm job response did not include a job id.")
        return TranscriptSubmission(
            job_id=job_id,
            source_url=source_url,
            task_ref=resolved_task_ref,
            job_payload=job_payload,
        )

    def complete_audio_job(
        self,
        audio: Audio,
        *,
        job_id: str,
        source_url: str,
        initial_job_payload: dict[str, Any] | None = None,
    ) -> TranscriptGenerationResult:
        job_payload = initial_job_payload or {}
        if str(job_payload.get("id", "")) != job_id:
            job_payload = {}
        if str(job_payload.get("state", "")) not in TERMINAL_JOB_STATES:
            job_payload = self.client.wait_for_job(job_id)
        if job_payload.get("state") != "succeeded":
            raise VoxhelmError(build_failure_message(job_payload))

        podlove = self.client.download_artifact(require_artifact_path(job_payload, "podlove"))
        dote = self.client.download_artifact(require_artifact_path(job_payload, "dote"))
        vtt = self.client.download_artifact(require_artifact_path(job_payload, "vtt"))
        speakers_path = optional_artifact_path(job_payload, "speakers")
        speakers = self.client.download_artifact(speakers_path) if speakers_path else None
        transcript, created = self._get_or_create_transcript(audio=audio)
        self._update_collection(transcript=transcript, audio=audio)
        self._save_artifacts(
            transcript=transcript, audio=audio, podlove=podlove, dote=dote, vtt=vtt, speakers=speakers
        )
        return TranscriptGenerationResult(
            transcript=transcript,
            created=created,
            job_id=job_id,
            source_url=source_url,
        )

    def generate_for_audio(
        self,
        audio: Audio,
        *,
        task_ref: str | None = None,
        episode: Any | None = None,
    ) -> TranscriptGenerationResult:
        submission = self.submit_for_audio(audio, task_ref=task_ref, episode=episode)
        return self.complete_audio_job(
            audio,
            job_id=submission.job_id,
            source_url=submission.source_url,
            initial_job_payload=submission.job_payload,
        )

    @staticmethod
    def _get_or_create_transcript(*, audio: Audio) -> tuple[Transcript, bool]:
        defaults: dict[str, Any] = {}
        if audio.collection_id is not None:
            defaults["collection"] = audio.collection
        return Transcript.objects.get_or_create(audio=audio, defaults=defaults)

    @staticmethod
    def _update_collection(*, transcript: Transcript, audio: Audio) -> None:
        if audio.collection_id is not None and transcript.collection_id != audio.collection_id:
            transcript.collection = audio.collection

    @staticmethod
    def _save_artifacts(
        *,
        transcript: Transcript,
        audio: Audio,
        podlove: bytes,
        dote: bytes,
        vtt: bytes,
        speakers: bytes | None = None,
    ) -> None:
        validate_transcript_artifacts(podlove=podlove, dote=dote, vtt=vtt, speakers=speakers)
        file_stem = f"audio-{audio.pk}"
        replacements = StagedFileReplacementGroup()
        try:
            replacements.stage(transcript.podlove, f"{file_stem}.podlove.json", podlove)
            replacements.stage(transcript.dote, f"{file_stem}.dote.json", dote)
            replacements.stage(transcript.vtt, f"{file_stem}.vtt", vtt)
            if speakers is not None:
                replacements.stage(transcript.speakers, f"{file_stem}.speakers.json", speakers)
            replacements.save_model(transcript)
        except Exception:
            replacements.rollback()
            raise


def enqueue_audio_transcript_generation(
    *,
    audio: Audio,
    request_or_site: HttpRequest | Site | None = None,
    requested_by=None,
    episode: Any | None = None,
) -> TranscriptEnqueueResult:
    if audio.pk is None:
        raise VoxhelmError("Audio must be saved before requesting a transcript.")

    generation = get_transcript_generation(audio)
    if generation is not None and generation.is_active:
        return TranscriptEnqueueResult(generation=generation, enqueued=False)

    service = VoxhelmTranscriptService(request_or_site=request_or_site)
    diarization_enabled = resolve_audio_diarization_enabled(audio, service.client)
    speaker_count = resolve_diarization_speaker_count(audio, episode=episode) if diarization_enabled else None
    task_ref = resolve_audio_task_ref(
        audio.pk,
        diarization_enabled=diarization_enabled,
        diarization_speaker_count=speaker_count,
    )
    generation, created = TranscriptGeneration.objects.get_or_create(
        audio=audio,
        defaults={"task_ref": task_ref},
    )
    if not created and generation.is_active:
        return TranscriptEnqueueResult(generation=generation, enqueued=False)

    try:
        submission = service.submit_for_audio(
            audio,
            task_ref=task_ref,
            episode=episode,
        )
    except Exception as exc:
        if created:
            generation.mark_failed(str(exc))
        raise
    site = request_or_site if isinstance(request_or_site, Site) else None
    generation.queue_submission(
        task_ref=submission.task_ref,
        voxhelm_job_id=submission.job_id,
        source_url=submission.source_url,
        task_result_id="",
        site=site,
        requested_by=requested_by,
    )
    # Deliberately imported at enqueue time: importing voxhelm_tasks requires the "cast_transcripts" TASKS backend to be configured (django-tasks resolves it at decoration).
    from ..voxhelm_tasks import complete_transcript_generation

    try:
        task_result = complete_transcript_generation.enqueue(generation.pk)
    except Exception as exc:
        generation.mark_failed(str(exc))
        raise
    generation.task_result_id = str(task_result.id)
    generation.save(update_fields=["task_result_id", "updated_at"])
    return TranscriptEnqueueResult(generation=generation, enqueued=True)
