from __future__ import annotations

import json
from time import monotonic, sleep
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from django.http import HttpRequest
from wagtail.models import Site

from .exceptions import VoxhelmError
from .settings import get_bool_setting, get_float_setting, get_setting, require_setting

TERMINAL_JOB_STATES = {"succeeded", "failed", "canceled", "expired"}
KNOWN_SPEAKER_STRATEGY = "pyannote_known_speaker"
MAX_VOXHELM_ARTIFACT_BYTES = 10 * 1024 * 1024
MAX_VOXHELM_API_RESPONSE_BYTES = 1024 * 1024
MAX_VOXHELM_ERROR_BYTES = 16 * 1024


if TYPE_CHECKING:
    from http.client import HTTPMessage
    from types import TracebackType
    from typing import IO, Protocol, Self, overload

    class ReadableResponse(Protocol):
        @overload
        def read(self) -> bytes: ...

        @overload
        def read(self, size: int, /) -> bytes: ...

        def __enter__(self) -> Self: ...

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> object: ...
else:
    ReadableResponse = Any


class NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> Request | None:
        return None


def open_url(request: Request, *, timeout: float, follow_redirects: bool = True) -> ReadableResponse:
    if follow_redirects:
        return urlopen(request, timeout=timeout)
    return build_opener(NoRedirectHandler).open(request, timeout=timeout)


def read_response_bytes(response: ReadableResponse, *, max_bytes: int | None = None) -> bytes:
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


def normalize_api_base(api_base: str) -> tuple[str, str]:
    normalized = api_base.rstrip("/")
    if normalized.endswith("/v1"):
        return normalized[: -len("/v1")], normalized
    return normalized, f"{normalized}/v1"


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
