"""One private, self-contained previous transcript version, swapped on restore."""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from cast.file_replacement import StagedFileReplacementGroup

from . import parsing, services

if TYPE_CHECKING:
    from cast.models.transcript import Transcript

MAX_VERSION_ARTIFACT_BYTES = 10 * 1024 * 1024
MAX_VERSION_TOTAL_BYTES = 30 * 1024 * 1024
MAX_VERSION_JSON_BYTES = 42 * 1024 * 1024

logger = logging.getLogger(__name__)

MAPPING_FIELDS = (
    "speaker_label",
    "contributor_id",
    "display_name",
    "review_state",
    "source_artifact_fingerprint",
    "active",
    "last_seen",
    "reviewed_at",
)


def bundle(transcript: Transcript) -> bytes:
    files = {}
    total = 0
    for name in services.EDITOR_ARTIFACT_FIELDS:
        field = getattr(transcript, name)
        if field:
            try:
                with field.storage.open(field.name, "rb") as file:
                    content = bytearray()
                    limit = min(MAX_VERSION_ARTIFACT_BYTES, MAX_VERSION_TOTAL_BYTES - total)
                    while chunk := file.read(min(64 * 1024, limit + 1 - len(content))):
                        content.extend(chunk)
                        if len(content) > limit:
                            raise ValidationError(
                                "Previous version exceeds the 10 MiB artifact or 30 MiB total limit."
                            )
            except FileNotFoundError:
                continue  # Only positively missing files may be omitted from recovery.
            except OSError as error:
                raise ValidationError("The current transcript files could not be backed up.") from error
            total += len(content)
            files[name] = {
                "name": field.name.rsplit("/", 1)[-1],
                "content": base64.b64encode(content).decode("ascii"),
            }
    mappings = list(transcript.speaker_mappings.values(*MAPPING_FIELDS))
    payload = json.dumps(
        {
            "version": 1,
            "saved_at": timezone.now().isoformat(),
            "files": files,
            "source_fingerprint": transcript.source_fingerprint,
            "mappings": mappings,
        },
        default=str,
    ).encode()
    if len(payload) > MAX_VERSION_JSON_BYTES:
        raise ValidationError("The previous version exceeds the 42 MiB backup limit.")
    return payload


@contextmanager
def _reserved(transcript: Transcript) -> Iterator[Transcript]:
    with transaction.atomic(using=transcript._state.db):
        if transcript.pk is None:
            yield transcript
            return
        type(transcript).objects.using(transcript._state.db).filter(pk=transcript.pk).update(
            source_fingerprint=models.F("source_fingerprint")
        )
        yield type(transcript).objects.using(transcript._state.db).get(pk=transcript.pk)


def _unwind(replacements: StagedFileReplacementGroup) -> None:
    # Called while handling an existing failure: cleanup must never replace it.
    try:
        replacements.rollback()
    except BaseException:
        logger.exception("Transcript version rollback cleanup failed; inspect staged recovery storage keys.")


@contextmanager
def replacing(transcript: Transcript) -> Iterator[None]:
    """Capture the committed state before upload/generation can delete its files."""
    replacements = StagedFileReplacementGroup()
    try:
        with _reserved(transcript) as stored:
            transcript.previous_version = stored.previous_version.name
            if stored.pk is not None and any(getattr(stored, name) for name in services.EDITOR_ARTIFACT_FIELDS):
                replacements.stage(transcript.previous_version, "previous.json", bundle(stored))
            yield
            if replacements.replacements:
                models.Model.save(transcript, update_fields=["previous_version"], using=transcript._state.db)
                transaction.on_commit(replacements.commit, using=transcript._state.db)
    except BaseException:
        _unwind(replacements)
        raise


def _validate_previous(data: Any) -> None:
    from cast.models.transcript import TranscriptSpeakerMapping

    if not isinstance(data, dict) or set(data) != {"version", "saved_at", "files", "source_fingerprint", "mappings"}:
        raise ValueError
    if type(data["version"]) is not int or data["version"] != 1:
        raise ValueError
    if not isinstance(data["files"], dict) or not isinstance(data["mappings"], list):
        raise ValueError
    if (
        not isinstance(data["source_fingerprint"], str)
        or len(data["source_fingerprint"]) > 64
        or "\x00" in data["source_fingerprint"]
    ):
        raise ValueError
    if not isinstance(data["saved_at"], str):
        raise ValueError
    datetime.fromisoformat(data["saved_at"])
    labels = set()
    for row in data["mappings"]:
        if not isinstance(row, dict) or set(row) != set(MAPPING_FIELDS):
            raise ValueError
        for name, maximum in (("speaker_label", 256), ("display_name", 128), ("source_artifact_fingerprint", 64)):
            value = row[name]
            if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
                raise ValueError
        label = row["speaker_label"]
        if not label or label != label.strip() or label in labels:
            raise ValueError
        labels.add(label)
        contributor = row["contributor_id"]
        if contributor is not None and (type(contributor) is not int or not 0 < contributor <= 2**63 - 1):
            raise ValueError
        if row["review_state"] not in TranscriptSpeakerMapping.ReviewState.values or type(row["active"]) is not bool:
            raise ValueError
        for name in ("last_seen", "reviewed_at"):
            if row[name] is not None:
                if not isinstance(row[name], str):
                    raise ValueError
                datetime.fromisoformat(row[name])
        if contributor is not None and row["display_name"].strip():
            raise ValueError
    total = 0
    for name, artifact in data["files"].items():
        if name not in services.EDITOR_ARTIFACT_FIELDS or not isinstance(artifact, dict):
            raise ValueError
        if set(artifact) != {"name", "content"}:
            raise ValueError
        filename = artifact["name"]
        if (
            not isinstance(filename, str)
            or not filename
            or len(filename) > 255
            or "/" in filename
            or "\\" in filename
            or "\x00" in filename
            or filename in {".", ".."}
        ):
            raise ValueError
        encoded = artifact["content"]
        if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_VERSION_ARTIFACT_BYTES + 2) // 3):
            raise ValueError
        content = base64.b64decode(encoded, validate=True)
        total += len(content)
        if len(content) > MAX_VERSION_ARTIFACT_BYTES or total > MAX_VERSION_TOTAL_BYTES:
            raise ValueError


def read_previous(transcript: Transcript) -> dict[str, Any]:
    if not transcript.previous_version:
        raise ValidationError("No previous version is available.")
    try:
        with transcript.previous_version.open("rb") as file:
            data = parsing.load_json_artifact(file, max_bytes=MAX_VERSION_JSON_BYTES)
        _validate_previous(data)
        return data
    except (OSError, ValueError, KeyError, TypeError, ValidationError, parsing.TranscriptArtifactError) as error:
        raise ValidationError("The previous version could not be read.") from error


def restore(transcript: Transcript) -> None:
    from cast.models import Contributor

    expected = services.artifact_state(transcript)
    replacements = StagedFileReplacementGroup()
    try:
        with _reserved(transcript) as stored:
            if (
                services.artifact_state(stored) != expected
                or stored.previous_version.name != transcript.previous_version.name
            ):
                raise services.TranscriptEditConflict("Reload the transcript; its previous version changed.")
            data = read_previous(stored)
            with replacing(transcript):
                for name in services.EDITOR_ARTIFACT_FIELDS:
                    artifact = data["files"].get(name)
                    if artifact:
                        replacements.stage(
                            getattr(transcript, name), artifact["name"], base64.b64decode(artifact["content"])
                        )
                    else:
                        setattr(transcript, name, "")
                transcript.source_fingerprint = data["source_fingerprint"]

                def save(instance: Transcript, **kwargs: Any) -> None:
                    kwargs["update_fields"] = [
                        *services.EDITOR_ARTIFACT_FIELDS,
                        "source_fingerprint",
                        "previous_version",
                    ]
                    instance.save(preserve_source_fingerprint=True, **kwargs)

                services.save_editor_artifacts(transcript, replacements, expected, save=save)
                transcript.speaker_mappings.all().delete()
                contributor_ids = {
                    row["contributor_id"] for row in data["mappings"] if row["contributor_id"] is not None
                }
                existing_contributors = Contributor.objects.using(stored._state.db).only("pk").in_bulk(contributor_ids)
                for row in data["mappings"]:
                    values = {name: row[name] for name in MAPPING_FIELDS}
                    if values["contributor_id"] is not None and values["contributor_id"] not in existing_contributors:
                        values.update(contributor_id=None, review_state="stale")
                    if values["review_state"] == "approved" and not (
                        values["contributor_id"] or values["display_name"]
                    ):
                        values["review_state"] = "stale"
                    transcript.speaker_mappings.create(**values)
    except BaseException:
        _unwind(replacements)
        raise
