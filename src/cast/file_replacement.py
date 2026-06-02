from __future__ import annotations

import re
from contextlib import suppress
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from django.core.files.base import ContentFile
from django.db import transaction

COMPOUND_SUFFIXES = (".podlove.json", ".dote.json", ".speakers.json")
GENERATED_SUFFIX_RE = re.compile(r"(?:-[0-9a-f]{12})+$")


@dataclass(frozen=True)
class StagedFileReplacement:
    field: Any
    old_storage: Any | None
    old_name: str
    new_storage: Any
    new_name: str


class StagedFileReplacementGroup:
    def __init__(self) -> None:
        self.replacements: list[StagedFileReplacement] = []
        self._rolled_back = False
        self._saved = False

    def stage(self, field: Any, filename: str, content: bytes) -> StagedFileReplacement:
        try:
            replacement = stage_file_replacement(field, filename, content)
        except Exception:
            self.rollback()
            raise
        self.replacements.append(replacement)
        return replacement

    def save_model(self, model: Any, *args: Any, **kwargs: Any) -> None:
        try:
            with transaction.atomic():
                model.save(*args, **kwargs)
                transaction.on_commit(self.delete_old_files)
        except Exception:
            self.rollback()
            raise
        self._saved = True

    def delete_old_files(self) -> None:
        for replacement in self.replacements:
            if replacement.old_name and replacement.old_name != replacement.new_name:
                _delete_file(replacement.old_storage, replacement.old_name)

    def rollback(self) -> None:
        if self._rolled_back or self._saved:
            return
        for replacement in reversed(self.replacements):
            if replacement.new_name and replacement.new_name != replacement.old_name:
                _delete_file(replacement.new_storage, replacement.new_name)
            _set_field_name(replacement.field, replacement.old_name)
        self._rolled_back = True


def stage_file_replacement(field: Any, filename: str, content: bytes) -> StagedFileReplacement:
    old_name = field.name if field and field.name else ""
    old_storage = field.storage if old_name else None
    storage = field.storage
    replacement_filename = fresh_file_name(filename)
    attempted_name = ""

    try:
        if old_name:
            attempted_name = _join_storage_name(_storage_dirname(old_name), _basename(replacement_filename))
            new_name = _save_to_storage(field, attempted_name, content)
            _set_field_name(field, new_name)
        else:
            attempted_name = replacement_filename
            field.save(replacement_filename, ContentFile(content), save=False)
            new_name = field.name
    except Exception:
        failed_name = field.name if field and field.name else ""
        if failed_name and failed_name != old_name:
            _delete_file(field.storage, failed_name)
        if attempted_name and attempted_name not in {old_name, failed_name}:
            _delete_file(storage, attempted_name)
        _set_field_name(field, old_name)
        raise

    return StagedFileReplacement(
        field=field,
        old_storage=old_storage,
        old_name=old_name,
        new_storage=field.storage,
        new_name=new_name,
    )


def fresh_file_name(name: str) -> str:
    directory = _storage_dirname(name)
    basename = _basename(name)
    unique_suffix = uuid4().hex[:12]

    for suffix in COMPOUND_SUFFIXES:
        if basename.endswith(suffix):
            stem = _strip_generated_suffix(basename[: -len(suffix)])
            return _join_storage_name(directory, f"{stem}-{unique_suffix}{suffix}")

    stem, dot, suffix = basename.rpartition(".")
    if dot:
        stem = _strip_generated_suffix(stem)
        return _join_storage_name(directory, f"{stem}-{unique_suffix}.{suffix}")
    return _join_storage_name(directory, f"{_strip_generated_suffix(basename)}-{unique_suffix}")


def _strip_generated_suffix(stem: str) -> str:
    return GENERATED_SUFFIX_RE.sub("", stem)


def _basename(name: str) -> str:
    return name.rsplit("/", 1)[-1]


def _storage_dirname(name: str) -> str:
    parts = name.rsplit("/", 1)
    return parts[0] if len(parts) == 2 else ""


def _join_storage_name(directory: str, basename: str) -> str:
    return f"{directory}/{basename}" if directory else basename


def _save_to_storage(field: Any, name: str, content: bytes) -> str:
    max_length = _field_max_length(field)
    if max_length is not None:
        return field.storage.save(name, ContentFile(content), max_length=max_length)
    return field.storage.save(name, ContentFile(content))


def _field_max_length(field: Any) -> int | None:
    model_field = getattr(field, "field", None)
    max_length = getattr(model_field, "max_length", None)
    return max_length if isinstance(max_length, int) else None


def _set_field_name(field: Any, name: str) -> None:
    if hasattr(field, "_file"):
        field.close()
        del field.file
    field.name = name
    if hasattr(field, "instance") and hasattr(field, "field"):
        setattr(field.instance, field.field.attname, name)
    if hasattr(field, "_committed"):
        field._committed = True


def _delete_file(storage: Any, name: str) -> None:
    with suppress(Exception):
        storage.delete(name)
