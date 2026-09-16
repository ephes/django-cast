"""Shared policy and transport primitives for media ingestion."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from django.core.cache import cache

from . import appsettings

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
