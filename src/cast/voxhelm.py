from __future__ import annotations

import json
import os
from dataclasses import dataclass
from time import monotonic, sleep
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile

from .models import Transcript

if TYPE_CHECKING:
    from .models import Audio

TERMINAL_JOB_STATES = {"succeeded", "failed", "canceled", "expired"}


class VoxhelmError(RuntimeError):
    """Raised when Voxhelm transcription or artifact retrieval fails."""


@dataclass(frozen=True)
class TranscriptGenerationResult:
    transcript: Transcript
    created: bool
    job_id: str
    source_url: str


def normalize_api_base(api_base: str) -> tuple[str, str]:
    normalized = api_base.rstrip("/")
    if normalized.endswith("/v1"):
        return normalized[: -len("/v1")], normalized
    return normalized, f"{normalized}/v1"


def get_setting(name: str, default: object = None) -> object:
    value = getattr(settings, name, None)
    if value not in {None, ""}:
        return value
    return os.getenv(name, default)


def require_setting(name: str) -> str:
    value = get_setting(name)
    if not isinstance(value, str) or not value.strip():
        raise ImproperlyConfigured(f"{name} must be configured as a Django setting or environment variable.")
    return value.strip()


def get_float_setting(name: str, default: float) -> float:
    return float(str(get_setting(name, default)))


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


def format_dote_timestamp(seconds: float) -> str:
    milliseconds = max(int(round(seconds * 1000)), 0)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{whole_seconds:02},{millis:03}"


def format_podlove_timestamp(seconds: float) -> str:
    milliseconds = max(int(round(seconds * 1000)), 0)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{whole_seconds:02}.{millis:03}"


def normalized_segments(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_segments = payload.get("segments")
    segments: list[dict[str, Any]] = []
    if isinstance(raw_segments, list):
        for index, raw_segment in enumerate(raw_segments):
            if not isinstance(raw_segment, dict):
                continue
            text = str(raw_segment.get("text", "")).strip()
            if not text:
                continue
            try:
                start = float(raw_segment.get("start", 0.0))
            except (TypeError, ValueError):
                continue
            try:
                end = float(raw_segment.get("end", start))
            except (TypeError, ValueError):
                end = start
            try:
                segment_id = int(raw_segment.get("id", index))
            except (TypeError, ValueError):
                segment_id = index
            segments.append(
                {
                    "id": segment_id,
                    "start": start,
                    "end": max(start, end),
                    "text": text,
                }
            )
    if segments:
        return segments
    text = str(payload.get("text", "")).strip()
    if text:
        return [{"id": 0, "start": 0.0, "end": 0.0, "text": text}]
    return []


def render_dote(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "lines": [
            {
                "startTime": format_dote_timestamp(segment["start"]),
                "endTime": format_dote_timestamp(segment["end"]),
                "speakerDesignation": "",
                "text": segment["text"],
            }
            for segment in normalized_segments(payload)
        ]
    }


def render_podlove(payload: dict[str, Any]) -> dict[str, Any]:
    transcripts = []
    for segment in normalized_segments(payload):
        start_ms = max(int(round(segment["start"] * 1000)), 0)
        end_ms = max(int(round(segment["end"] * 1000)), 0)
        transcripts.append(
            {
                "start": format_podlove_timestamp(segment["start"]),
                "start_ms": start_ms,
                "end": format_podlove_timestamp(segment["end"]),
                "end_ms": end_ms,
                "speaker": "",
                "voice": "",
                "text": segment["text"],
            }
        )
    return {"version": 1, "transcripts": transcripts}


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
    if field.name:
        field.delete(save=False)
    field.save(filename, ContentFile(content), save=False)


class VoxhelmClient:
    def __init__(
        self,
        *,
        api_base: str,
        api_key: str,
        poll_interval_seconds: float = 2.0,
        job_timeout_seconds: float = 900.0,
        request_timeout_seconds: float = 30.0,
    ) -> None:
        self.root_url, self.api_base = normalize_api_base(api_base)
        self.api_key = api_key
        self.poll_interval_seconds = poll_interval_seconds
        self.job_timeout_seconds = job_timeout_seconds
        self.request_timeout_seconds = request_timeout_seconds

    @classmethod
    def from_settings(cls) -> VoxhelmClient:
        return cls(
            api_base=require_setting("CAST_VOXHELM_API_BASE"),
            api_key=require_setting("CAST_VOXHELM_API_KEY"),
            poll_interval_seconds=get_float_setting("CAST_VOXHELM_POLL_INTERVAL", 2.0),
            job_timeout_seconds=get_float_setting("CAST_VOXHELM_POLL_TIMEOUT", 900.0),
            request_timeout_seconds=get_float_setting("CAST_VOXHELM_REQUEST_TIMEOUT", 30.0),
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

    def request_bytes(self, *, method: str, path: str, payload: dict[str, Any] | None = None) -> bytes:
        url = self.build_url(path)
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {}
        if self.should_send_auth(url):
            headers["Authorization"] = f"Bearer {self.api_key}"
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.request_timeout_seconds) as response:
                return response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip() or str(exc.reason)
            raise VoxhelmError(f"Voxhelm request failed with status {exc.code}: {detail}") from exc
        except URLError as exc:
            raise VoxhelmError(f"Voxhelm request failed: {exc.reason}") from exc

    def request_json(self, *, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        raw = self.request_bytes(method=method, path=path, payload=payload)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise VoxhelmError("Voxhelm returned a non-object JSON payload.")
        return data

    def submit_transcription_job(self, *, source_url: str, task_ref: str, context: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "job_type": "transcribe",
            "priority": "normal",
            "lane": "batch",
            "backend": "auto",
            "model": str(get_setting("CAST_VOXHELM_MODEL", "auto")),
            "input": {"kind": "url", "url": source_url},
            "output": {"formats": ["json", "vtt"]},
            "context": context,
            "task_ref": task_ref,
        }
        language = get_setting("CAST_VOXHELM_LANGUAGE")
        if isinstance(language, str) and language.strip():
            payload["language"] = language.strip()
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
        return self.request_bytes(method="GET", path=artifact_path)


class VoxhelmTranscriptService:
    def __init__(self, *, client: VoxhelmClient | None = None) -> None:
        self.client = client or VoxhelmClient.from_settings()

    def generate_for_audio(self, audio: Audio, *, task_ref: str | None = None) -> TranscriptGenerationResult:
        if audio.pk is None:
            raise VoxhelmError("Audio must be saved before requesting a transcript.")

        source_url = resolve_audio_source_url(audio)
        job_payload = self.client.submit_transcription_job(
            source_url=source_url,
            task_ref=task_ref or f"cast-audio-{audio.pk}",
            context={"consumer": "django-cast", "audio_id": audio.pk},
        )
        job_id = str(job_payload.get("id", ""))
        if str(job_payload.get("state", "")) not in TERMINAL_JOB_STATES:
            job_payload = self.client.wait_for_job(job_id)
        if job_payload.get("state") != "succeeded":
            raise VoxhelmError(build_failure_message(job_payload))

        verbose_json = json.loads(self.client.download_artifact(require_artifact_path(job_payload, "json")))
        if not isinstance(verbose_json, dict):
            raise VoxhelmError("Voxhelm transcript JSON artifact was not an object.")
        vtt = self.client.download_artifact(require_artifact_path(job_payload, "vtt"))
        transcript, created = self._get_or_create_transcript(audio=audio)
        self._update_collection(transcript=transcript, audio=audio)
        self._save_artifacts(transcript=transcript, audio=audio, verbose_json=verbose_json, vtt=vtt)
        return TranscriptGenerationResult(
            transcript=transcript,
            created=created,
            job_id=job_id,
            source_url=source_url,
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
        verbose_json: dict[str, Any],
        vtt: bytes,
    ) -> None:
        file_stem = f"audio-{audio.pk}"
        replace_file(
            transcript.podlove,
            f"{file_stem}.podlove.json",
            json.dumps(render_podlove(verbose_json), ensure_ascii=True, indent=2).encode("utf-8"),
        )
        replace_file(
            transcript.dote,
            f"{file_stem}.dote.json",
            json.dumps(render_dote(verbose_json), ensure_ascii=True, indent=2).encode("utf-8"),
        )
        replace_file(transcript.vtt, f"{file_stem}.vtt", vtt)
        transcript.save()
