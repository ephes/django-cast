"""Shared policy and transport primitives for media ingestion."""

from __future__ import annotations

import logging
import subprocess
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from typing import Any

from django.core.cache import cache
from django.db import transaction

from . import appsettings
from .file_replacement import FileFieldReplacementGuard, fresh_file_name
from .media_derivation import normalize_model_save_arguments
from .media_probe import media_probe_budget
from .models.audio import AudioDurationProbeError, AudioDurationProbeTimeout

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestPolicy:
    """Bound cumulative probe work and identify stored file fields."""

    probe_seconds: float | None
    file_fields: tuple[str, ...]


class MediaIngestError(Exception):
    """Base class for failures at the media-ingestion boundary."""


class MediaUploadInProgress(MediaIngestError):
    """The user already has a media upload in progress."""


class MediaProbeTimeout(MediaIngestError):
    """Media probing exceeded the cumulative ingest budget."""


class MediaProbeFailed(MediaIngestError):
    """Required media probing failed."""


class MediaIngestCleanupFailed(MediaIngestError):
    """An ingest failure could not clean up newly written files."""


def editor_policy(file_fields: tuple[str, ...]) -> IngestPolicy:
    """Build the editor upload policy from current settings."""
    return IngestPolicy(float(appsettings.CAST_EDITOR_MEDIA_PROBE_SECONDS), file_fields)


def admin_policy(file_fields: tuple[str, ...]) -> IngestPolicy:
    """Build the admin upload policy from current settings."""
    return IngestPolicy(float(appsettings.CAST_MEDIA_PROBE_SECONDS), file_fields)


TRANSCRIPT_POLICY = IngestPolicy(probe_seconds=None, file_fields=("podlove", "dote", "vtt"))


@contextmanager
def upload_lock(user: Any, *, seconds: int | None = None) -> Iterator[None]:
    """Serialize audio and video uploads for one user."""
    key = f"cast:editor-media-upload:{user.pk}"
    owner = uuid.uuid4().hex
    timeout = int(appsettings.CAST_EDITOR_MEDIA_UPLOAD_LOCK_SECONDS if seconds is None else seconds)
    if not cache.add(key, owner, timeout=timeout):
        raise MediaUploadInProgress
    try:
        yield
    finally:
        if cache.get(key) == owner:
            cache.delete(key)


def _delete_field_file(field: Any) -> None:
    if getattr(field, "name", ""):
        field.delete(save=False)


def cleanup_new_media_object(obj: Any, field_names: tuple[str, ...]) -> bool:
    """Remove files and a row created by an unsuccessful ingest."""
    try:
        for field_name in field_names:
            _delete_field_file(getattr(obj, field_name))
        if getattr(obj, "pk", None) is not None:
            obj.delete()
    except Exception:
        logger.exception("Media ingest cleanup failed for %s pk=%s", obj._meta.label, getattr(obj, "pk", None))
        return False
    return True


def _rename_uncommitted_files(instance: Any, field_names: tuple[str, ...]) -> None:
    for field_name in field_names:
        field = getattr(instance, field_name)
        if field and not field._committed:
            field.name = fresh_file_name(field.name)


def ingest_upload(form: Any, *, policy: IngestPolicy) -> Any:
    """Persist a validated create form under the shared ingest policy.

    Probing intentionally stays inside the transaction so the row, form-owned
    relations, and synchronous derivations either commit together or roll back.
    """
    instance = form.instance
    _rename_uncommitted_files(instance, policy.file_fields)
    _, using = normalize_model_save_arguments(instance, (), {})
    probe_budget = nullcontext() if policy.probe_seconds is None else media_probe_budget(policy.probe_seconds)
    is_replacement = instance.pk is not None
    replacement_guard: FileFieldReplacementGuard | None = None

    try:
        with probe_budget, transaction.atomic(using=using):
            if is_replacement:
                replacement_guard = FileFieldReplacementGuard.track(instance, policy.file_fields, using=using)
            result = form.save()
            if replacement_guard is not None:
                replacement_guard.commit()
            return result
    except Exception as exc:
        try:
            if replacement_guard is not None:
                replacement_guard.rollback()
                cleanup_succeeded = True
            elif is_replacement:
                # Tracking failed before form.save(), so no new file was written.
                cleanup_succeeded = True
            else:
                cleanup_succeeded = cleanup_new_media_object(instance, policy.file_fields)
        except Exception:
            logger.exception(
                "Media ingest rollback cleanup failed for %s pk=%s",
                instance._meta.label,
                getattr(instance, "pk", None),
            )
            cleanup_succeeded = False
        if not cleanup_succeeded:
            logger.exception(
                "Media ingest failed before cleanup completed for %s pk=%s",
                instance._meta.label,
                getattr(instance, "pk", None),
            )
            raise MediaIngestCleanupFailed("Media ingest cleanup failed.") from exc
        if isinstance(exc, (subprocess.TimeoutExpired, AudioDurationProbeTimeout)):
            raise MediaProbeTimeout("Media probing exceeded the ingest budget.") from exc
        if isinstance(exc, AudioDurationProbeError):
            raise MediaProbeFailed("Media probing failed.") from exc
        raise
