from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from time import monotonic, sleep
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest
from django.urls import reverse
from wagtail.models import Site

from .file_replacement import StagedFileReplacementGroup, stage_file_replacement
from .models import Transcript, TranscriptGeneration

if TYPE_CHECKING:
    from .models import Audio

TERMINAL_JOB_STATES = {"succeeded", "failed", "canceled", "expired"}
SITE_SETTING_FIELD_MAP = {
    "CAST_VOXHELM_API_BASE": "api_base",
    "CAST_VOXHELM_API_KEY": "api_token",
    "CAST_VOXHELM_MODEL": "model",
    "CAST_VOXHELM_LANGUAGE": "language",
    "CAST_VOXHELM_DIARIZATION_ENABLED": "diarization_enabled",
    "CAST_VOXHELM_KNOWN_SPEAKER_ENABLED": "known_speaker_enabled",
}
KNOWN_SPEAKER_STRATEGY = "pyannote_known_speaker"
TRUE_SETTING_VALUES = {"1", "true", "yes", "on"}
FALSE_SETTING_VALUES = {"0", "false", "no", "off"}
MAX_VOXHELM_ARTIFACT_BYTES = 10 * 1024 * 1024
MAX_VOXHELM_API_RESPONSE_BYTES = 1024 * 1024
MAX_VOXHELM_ERROR_BYTES = 16 * 1024
DOTE_REQUIRED_KEYS = {"startTime", "endTime", "speakerDesignation", "text"}


class VoxhelmError(RuntimeError):
    """Raised when Voxhelm transcription or artifact retrieval fails."""


class NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def open_url(request: Request, *, timeout: float, follow_redirects: bool = True):
    if follow_redirects:
        return urlopen(request, timeout=timeout)
    return build_opener(NoRedirectHandler).open(request, timeout=timeout)


def read_response_bytes(response, *, max_bytes: int | None = None) -> bytes:
    if max_bytes is None:
        return response.read()
    data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise VoxhelmError(f"Voxhelm response exceeded the maximum size of {max_bytes} bytes.")
    return data


def read_http_error_detail(exc: HTTPError) -> str:
    data = exc.read(MAX_VOXHELM_ERROR_BYTES + 1)
    if len(data) > MAX_VOXHELM_ERROR_BYTES:
        data = data[:MAX_VOXHELM_ERROR_BYTES]
        suffix = " [truncated]"
    else:
        suffix = ""
    detail = data.decode("utf-8", errors="replace").strip() or str(exc.reason)
    return f"{detail}{suffix}"


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


def normalize_api_base(api_base: str) -> tuple[str, str]:
    normalized = api_base.rstrip("/")
    if normalized.endswith("/v1"):
        return normalized[: -len("/v1")], normalized
    return normalized, f"{normalized}/v1"


def get_site_setting_value(name: str, request_or_site: HttpRequest | Site | None) -> object:
    field_name = SITE_SETTING_FIELD_MAP.get(name)
    if field_name is None or request_or_site is None:
        return None

    from .models import VoxhelmSettings

    if isinstance(request_or_site, Site):
        site_settings = VoxhelmSettings.for_site(request_or_site)
    else:
        site_settings = VoxhelmSettings.for_request(request_or_site)
    value = getattr(site_settings, field_name, "")
    if isinstance(value, str):
        return value.strip()
    return value


def get_setting(name: str, default: object = None, *, request_or_site: HttpRequest | Site | None = None) -> object:
    site_value = get_site_setting_value(name, request_or_site)
    if site_value not in {None, ""}:
        return site_value
    value = getattr(settings, name, None)
    if value not in {None, ""}:
        return value
    return os.getenv(name, default)


def require_setting(name: str, *, request_or_site: HttpRequest | Site | None = None) -> str:
    value = get_setting(name, request_or_site=request_or_site)
    if not isinstance(value, str) or not value.strip():
        raise ImproperlyConfigured(f"{name} must be configured as a Django setting or environment variable.")
    return value.strip()


def get_float_setting(name: str, default: float, *, request_or_site: HttpRequest | Site | None = None) -> float:
    value = get_setting(name, default, request_or_site=request_or_site)
    try:
        return float(str(value))
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(
            f"{name} must be configured as a numeric value in seconds through a Django setting or environment variable."
        ) from exc


def get_bool_setting(name: str, default: bool = False, *, request_or_site: HttpRequest | Site | None = None) -> bool:
    value = get_setting(name, default, request_or_site=request_or_site)
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized:
            return default
        if normalized in TRUE_SETTING_VALUES:
            return True
        if normalized in FALSE_SETTING_VALUES:
            return False
    raise ImproperlyConfigured(
        f"{name} must be configured as a boolean value: one of 1, true, yes, on, 0, false, no, or off."
    )


def transcript_complete(transcript: Transcript) -> bool:
    if not (transcript.podlove and transcript.vtt and transcript.dote):
        return False
    podlove_transcripts = transcript.podlove_data.get("transcripts")
    dote_lines = transcript.dote_data.get("lines")
    return bool(podlove_transcripts) and bool(dote_lines)


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


def build_audio_task_ref(
    audio_id: int,
    *,
    diarization_enabled: bool = False,
    diarization_speaker_count: int | None = None,
) -> str:
    task_ref = f"cast-audio-{audio_id}"
    if not diarization_enabled:
        return task_ref
    task_ref = f"{task_ref}-diarized"
    if diarization_speaker_count is not None:
        task_ref = f"{task_ref}-{diarization_speaker_count}-speakers"
    return task_ref


def append_diarization_speaker_count_to_task_ref(task_ref: str, speaker_count: int | None) -> str:
    if speaker_count is None:
        return task_ref
    suffix = f"-{speaker_count}-speakers"
    if task_ref.endswith(suffix):
        return task_ref
    if re.search(r"-diarized-\d+-speakers$", task_ref):
        return re.sub(r"-\d+-speakers$", suffix, task_ref)
    return f"{task_ref}{suffix}"


def ensure_diarized_task_ref(task_ref: str) -> str:
    if re.search(r"-diarized(?:-\d+-speakers)?$", task_ref):
        return task_ref
    return f"{task_ref}-diarized"


def strip_diarized_task_ref(task_ref: str) -> str:
    return re.sub(r"-diarized(?:-\d+-speakers)?$", "", task_ref)


def resolve_audio_task_ref(
    audio_id: int,
    *,
    task_ref: str | None = None,
    diarization_enabled: bool = False,
    diarization_speaker_count: int | None = None,
) -> str:
    if task_ref is None:
        return build_audio_task_ref(
            audio_id,
            diarization_enabled=diarization_enabled,
            diarization_speaker_count=diarization_speaker_count,
        )
    if not diarization_enabled:
        return strip_diarized_task_ref(task_ref)
    return append_diarization_speaker_count_to_task_ref(
        ensure_diarized_task_ref(task_ref),
        diarization_speaker_count,
    )


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
    opted into hidden-contributor use. References resolve to absolute reference
    audio URLs (source ranges into existing audio, or uploaded clips); any
    reference without a resolvable URL is skipped.
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

    from .models.contributors import ContributorVoiceReference

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
        url = getattr(reference.clip, "url", "")
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


class VoxhelmClient:
    def __init__(
        self,
        *,
        api_base: str,
        api_key: str,
        model: str = "auto",
        language: str = "",
        diarization_enabled: bool = False,
        known_speaker_enabled: bool = False,
        poll_interval_seconds: float = 2.0,
        job_timeout_seconds: float = 900.0,
        request_timeout_seconds: float = 30.0,
    ) -> None:
        if not isinstance(diarization_enabled, bool):
            raise TypeError("diarization_enabled must be a bool.")
        if not isinstance(known_speaker_enabled, bool):
            raise TypeError("known_speaker_enabled must be a bool.")
        self.root_url, self.api_base = normalize_api_base(api_base)
        self.api_key = api_key
        self.model = model
        self.language = language
        self.diarization_enabled = diarization_enabled
        self.known_speaker_enabled = known_speaker_enabled
        self.poll_interval_seconds = poll_interval_seconds
        self.job_timeout_seconds = job_timeout_seconds
        self.request_timeout_seconds = request_timeout_seconds

    @classmethod
    def from_settings(cls, *, request_or_site: HttpRequest | Site | None = None) -> VoxhelmClient:
        return cls(
            api_base=require_setting("CAST_VOXHELM_API_BASE", request_or_site=request_or_site),
            api_key=require_setting("CAST_VOXHELM_API_KEY", request_or_site=request_or_site),
            model=str(get_setting("CAST_VOXHELM_MODEL", "auto", request_or_site=request_or_site)).strip() or "auto",
            language=str(get_setting("CAST_VOXHELM_LANGUAGE", "", request_or_site=request_or_site)).strip(),
            diarization_enabled=get_bool_setting(
                "CAST_VOXHELM_DIARIZATION_ENABLED", False, request_or_site=request_or_site
            ),
            known_speaker_enabled=get_bool_setting(
                "CAST_VOXHELM_KNOWN_SPEAKER_ENABLED", False, request_or_site=request_or_site
            ),
            poll_interval_seconds=get_float_setting(
                "CAST_VOXHELM_POLL_INTERVAL", 2.0, request_or_site=request_or_site
            ),
            job_timeout_seconds=get_float_setting("CAST_VOXHELM_POLL_TIMEOUT", 900.0, request_or_site=request_or_site),
            request_timeout_seconds=get_float_setting(
                "CAST_VOXHELM_REQUEST_TIMEOUT", 30.0, request_or_site=request_or_site
            ),
        )

    def build_url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        if path.startswith("/"):
            return f"{self.root_url}{path}"
        return f"{self.api_base}/{path.lstrip('/')}"

    def should_send_auth(self, url: str) -> bool:
        root_parts = urlsplit(self.root_url)
        target_parts = urlsplit(url)
        return (target_parts.scheme, target_parts.netloc) == (root_parts.scheme, root_parts.netloc)

    def build_artifact_url(self, artifact_path: str) -> str:
        url = self.build_url(artifact_path)
        if not self.should_send_auth(url):
            raise VoxhelmError("Voxhelm artifact URL must be relative or use the configured Voxhelm origin.")
        return url

    def request_bytes(
        self,
        *,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        max_bytes: int | None = None,
        follow_redirects: bool = True,
    ) -> bytes:
        url = self.build_url(path)
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {}
        if self.should_send_auth(url):
            headers["Authorization"] = f"Bearer {self.api_key}"
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with open_url(
                request, timeout=self.request_timeout_seconds, follow_redirects=follow_redirects
            ) as response:
                return read_response_bytes(response, max_bytes=max_bytes)
        except HTTPError as exc:
            detail = read_http_error_detail(exc)
            raise VoxhelmError(f"Voxhelm request failed with status {exc.code}: {detail}") from exc
        except URLError as exc:
            raise VoxhelmError(f"Voxhelm request failed: {exc.reason}") from exc

    def request_json(self, *, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        raw = self.request_bytes(
            method=method,
            path=path,
            payload=payload,
            max_bytes=MAX_VOXHELM_API_RESPONSE_BYTES,
            follow_redirects=False,
        )
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise VoxhelmError("Voxhelm returned a non-object JSON payload.")
        return data

    def submit_transcription_job(
        self,
        *,
        source_url: str,
        task_ref: str,
        context: dict[str, Any],
        speaker_count: int | None = None,
        diarization_enabled: bool | None = None,
        known_speakers: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if speaker_count is not None and (
            not isinstance(speaker_count, int) or isinstance(speaker_count, bool) or speaker_count < 1
        ):
            raise VoxhelmError("speaker_count must be a positive integer when provided.")
        send_diarization = self.diarization_enabled if diarization_enabled is None else diarization_enabled
        if not isinstance(send_diarization, bool):
            raise TypeError("diarization_enabled must be a bool when provided.")
        payload = {
            "job_type": "transcribe",
            "priority": "normal",
            "lane": "batch",
            "backend": "auto",
            "model": self.model,
            "input": {"kind": "url", "url": source_url},
            "output": {"formats": ["podlove", "dote", "vtt"]},
            "context": context,
            "task_ref": task_ref,
        }
        if self.language:
            payload["language"] = self.language
        if send_diarization:
            diarization: dict[str, Any] = {"enabled": True}
            if speaker_count is not None:
                diarization["num_speakers"] = speaker_count
            if known_speakers:
                diarization["strategy"] = KNOWN_SPEAKER_STRATEGY
                diarization["known_speakers"] = known_speakers
            payload["diarization"] = diarization
        return self.request_json(method="POST", path="jobs", payload=payload)

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self.request_json(method="GET", path=f"jobs/{job_id}")

    def wait_for_job(self, job_id: str) -> dict[str, Any]:
        deadline = monotonic() + self.job_timeout_seconds
        while True:
            job_payload = self.get_job(job_id)
            state = str(job_payload.get("state", ""))
            if state in TERMINAL_JOB_STATES:
                return job_payload
            if monotonic() >= deadline:
                raise VoxhelmError(f"Timed out waiting for Voxhelm job {job_id}.")
            sleep(self.poll_interval_seconds)

    def download_artifact(self, artifact_path: str) -> bytes:
        return self.request_bytes(
            method="GET",
            path=self.build_artifact_url(artifact_path),
            max_bytes=MAX_VOXHELM_ARTIFACT_BYTES,
            follow_redirects=False,
        )


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
    from .voxhelm_tasks import complete_transcript_generation

    try:
        task_result = complete_transcript_generation.enqueue(generation.pk)
    except Exception as exc:
        generation.mark_failed(str(exc))
        raise
    generation.task_result_id = str(task_result.id)
    generation.save(update_fields=["task_result_id", "updated_at"])
    return TranscriptEnqueueResult(generation=generation, enqueued=True)
