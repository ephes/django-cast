"""One private, self-contained previous transcript version, swapped on restore."""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from cast.file_replacement import StagedFileReplacementGroup

from . import services

if TYPE_CHECKING:
    from cast.models.transcript import Transcript

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
    for name in services.EDITOR_ARTIFACT_FIELDS:
        field = getattr(transcript, name)
        if field:
            with field.storage.open(field.name, "rb") as file:
                files[name] = {
                    "name": field.name.rsplit("/", 1)[-1],
                    "content": base64.b64encode(file.read()).decode("ascii"),
                }
    mappings = list(transcript.speaker_mappings.values(*MAPPING_FIELDS))
    return json.dumps(
        {
            "version": 1,
            "saved_at": timezone.now().isoformat(),
            "files": files,
            "source_fingerprint": transcript.source_fingerprint,
            "mappings": mappings,
        },
        default=str,
    ).encode()


@contextmanager
def replacing(transcript: Transcript) -> Iterator[None]:
    """Capture the committed state before upload/generation can delete its files."""
    replacements = StagedFileReplacementGroup()
    try:
        with transaction.atomic(using=transcript._state.db):
            if transcript.pk is not None:
                type(transcript).objects.using(transcript._state.db).filter(pk=transcript.pk).update(
                    source_fingerprint=models.F("source_fingerprint")
                )
                stored = type(transcript).objects.using(transcript._state.db).get(pk=transcript.pk)
                transcript.previous_version = stored.previous_version.name
                if any(getattr(stored, name) for name in services.EDITOR_ARTIFACT_FIELDS):
                    replacements.stage(transcript.previous_version, "previous.json", bundle(stored))
            yield
            if replacements.replacements:
                models.Model.save(transcript, update_fields=["previous_version"], using=transcript._state.db)
                transaction.on_commit(replacements.delete_old_files, using=transcript._state.db)
    except Exception:
        replacements.rollback()
        raise


def read_previous(transcript: Transcript) -> dict[str, Any]:
    if not transcript.previous_version:
        raise ValidationError("No previous version is available.")
    try:
        with transcript.previous_version.open("rb") as file:
            data = json.load(file)
        if data["version"] != 1 or not isinstance(data["files"], dict) or not isinstance(data["mappings"], list):
            raise ValueError
        if not isinstance(data["source_fingerprint"], str) or not isinstance(data["saved_at"], str):
            raise ValueError
        if any(
            not isinstance(row, dict) or any(name not in row for name in MAPPING_FIELDS) for row in data["mappings"]
        ):
            raise ValueError
        for name, artifact in data["files"].items():
            if name not in services.EDITOR_ARTIFACT_FIELDS or not isinstance(artifact["name"], str):
                raise ValueError
            base64.b64decode(artifact["content"], validate=True)
        return data
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValidationError("The previous version could not be read.") from error


def restore(transcript: Transcript) -> None:
    from cast.models import Contributor

    data = read_previous(transcript)
    expected = services.artifact_state(transcript)
    replacements = StagedFileReplacementGroup()
    try:
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
                kwargs["update_fields"] = [*services.EDITOR_ARTIFACT_FIELDS, "source_fingerprint", "previous_version"]
                instance.save(preserve_source_fingerprint=True, **kwargs)

            services.save_editor_artifacts(transcript, replacements, expected, save=save)
            transcript.speaker_mappings.all().delete()
            for row in data["mappings"]:
                values = {name: row[name] for name in MAPPING_FIELDS}
                if (
                    values["contributor_id"]
                    and not Contributor.objects.using(transcript._state.db)
                    .filter(pk=values["contributor_id"])
                    .exists()
                ):
                    values.update(contributor_id=None, review_state="stale")
                transcript.speaker_mappings.create(**values)
    except Exception:
        replacements.rollback()
        raise
