from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from django.core.files.base import ContentFile
from django.db import DEFAULT_DB_ALIAS, models, transaction

from cast.media_derivation import normalize_model_save_arguments

COMPOUND_SUFFIXES = (".podlove.json", ".dote.json", ".speakers.json", ".corrections.json")
GENERATED_SUFFIX_RE = re.compile(r"(?:-[0-9a-f]{12})+$")


class FileReplacementConflict(ValueError):
    """The stored media generation changed since this editor loaded it."""


def _lock_current_row(instance: Any, *, using: str) -> Any:
    manager = type(instance)._default_manager.using(using)
    # A no-op write also obtains SQLite's write lock before reading a snapshot.
    # PostgreSQL holds this row lock until the surrounding save transaction exits.
    manager.filter(pk=instance.pk).update(**{instance._meta.pk.name: models.F(instance._meta.pk.name)})
    stored = manager.get(pk=instance.pk)
    if getattr(stored, "modified", None) != getattr(instance, "modified", None):
        raise FileReplacementConflict("Media changed while editing; reload before replacing files.")
    return stored


@dataclass(frozen=True)
class StagedFileReplacement:
    field: Any
    old_storage: Any | None
    old_name: str
    new_storage: Any
    new_name: str


class StagedFileReplacementGroup:
    """Stage files for one save attempt; create a fresh group for each attempt."""

    def __init__(self) -> None:
        self.replacements: list[StagedFileReplacement] = []
        self._rolled_back = False
        self._saved = False
        self._pending_using: str | None = None
        self._scope_using: str | None = None

    @contextmanager
    def rollback_scope(self, *, using: str = DEFAULT_DB_ALIAS) -> Iterator[StagedFileReplacementGroup]:
        """Own the outermost transaction and clean staged files after rollback.

        Place any additional atomic blocks inside this scope. Django's durable
        boundary refuses an already-active application transaction before staging.
        """
        try:
            with transaction.atomic(using=using, durable=True):
                self._scope_using = using
                yield self
        finally:
            self._scope_using = None
            self.rollback()

    def stage(self, field: Any, filename: str, content: bytes) -> StagedFileReplacement:
        try:
            replacement = stage_file_replacement(field, filename, content)
        except Exception:
            self.rollback()
            raise
        self.replacements.append(replacement)
        return replacement

    def save_model(
        self,
        model: Any,
        *args: Any,
        save: Callable[..., None] | None = None,
        **kwargs: Any,
    ) -> None:
        save_kwargs, using = normalize_model_save_arguments(model, args, kwargs)
        try:
            if self._scope_using is not None and using != self._scope_using:
                raise ValueError("A replacement scope must use the model's database.")
            with transaction.atomic(using=using):
                if getattr(model, "pk", None) is not None:
                    stored = _lock_current_row(model, using=using)
                    expected_names: dict[str, str] = {}
                    for replacement in self.replacements:
                        expected_names.setdefault(replacement.field.field.name, replacement.old_name)
                    if any((getattr(stored, name).name or "") != old for name, old in expected_names.items()):
                        raise FileReplacementConflict(
                            "Media files changed while editing; reload before replacing files."
                        )
                if save is None:
                    model.save(**save_kwargs)
                else:
                    save(model, **save_kwargs)
                self._pending_using = using
                transaction.on_commit(self._commit, using=using)
        except Exception:
            self.rollback()
            raise

    def _commit(self) -> None:
        if self._rolled_back:
            return
        self._saved = True
        self.delete_old_files()

    def delete_old_files(self) -> None:
        for replacement in self.replacements:
            if replacement.old_name and replacement.old_name != replacement.new_name:
                _delete_file(replacement.old_storage, replacement.old_name)

    def rollback(self) -> None:
        if self._rolled_back or self._saved:
            return
        if self._pending_using is not None and transaction.get_connection(self._pending_using).in_atomic_block:
            raise RuntimeError("Exit the owning transaction before rolling back replacement files.")
        for replacement in reversed(self.replacements):
            if replacement.new_name and replacement.new_name != replacement.old_name:
                _delete_file(replacement.new_storage, replacement.new_name)
            _set_field_name(replacement.field, replacement.old_name)
        self._rolled_back = True


@dataclass(frozen=True)
class _FileFieldSnapshot:
    field: Any
    old_storage: Any
    old_name: str


class FileFieldReplacementGuard:
    """Keep stored files consistent with an existing model row."""

    def __init__(self, snapshots: list[_FileFieldSnapshot], *, using: str) -> None:
        self.snapshots = snapshots
        self.using = using
        self._rolled_back = False

    @classmethod
    def track(cls, instance: Any, field_names: tuple[str, ...], *, using: str) -> FileFieldReplacementGuard:
        stored = _lock_current_row(instance, using=using)
        stored_names = [getattr(stored, name).name for name in field_names]
        snapshots = [
            _FileFieldSnapshot(
                field=getattr(instance, field_name),
                old_storage=getattr(instance, field_name).storage,
                old_name=stored_name or "",
            )
            for field_name, stored_name in zip(field_names, stored_names, strict=True)
        ]
        return cls(snapshots, using=using)

    def commit(self) -> None:
        replacements = [
            (snapshot.old_storage, snapshot.old_name)
            for snapshot in self.snapshots
            if snapshot.old_name and snapshot.old_name != (snapshot.field.name or "")
        ]

        if not replacements:
            return

        def delete_old_files() -> None:
            for old_storage, old_name in replacements:
                _delete_file(old_storage, old_name)

        transaction.on_commit(delete_old_files, using=self.using)

    def rollback(self) -> None:
        if self._rolled_back:
            return
        cleanup_errors: list[Exception] = []
        for snapshot in reversed(self.snapshots):
            new_name = snapshot.field.name or ""
            # Django sets _committed only after storage.save() returns successfully.
            if new_name and new_name != snapshot.old_name and snapshot.field._committed:
                try:
                    _delete_file_strict(snapshot.field.storage, new_name)
                except Exception as exc:
                    cleanup_errors.append(exc)
            _set_field_name(snapshot.field, snapshot.old_name)
        self._rolled_back = True
        if cleanup_errors:
            raise cleanup_errors[0]


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


def _delete_file_strict(storage: Any, name: str) -> None:
    storage.delete(name)
