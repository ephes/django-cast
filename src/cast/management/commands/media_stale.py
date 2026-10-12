from argparse import ArgumentParser
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta
from typing import Any

from django.apps import apps
from django.core.files.storage import Storage
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connections, models, router, transaction
from django.utils import timezone

from ...utils import storage_walk_paths
from .storage_backend import get_production_and_backup_storage

MANAGED_MEDIA_PREFIXES = (
    "cast_audio/",
    "cast_files/",
    "cast_images/",
    "cast_transcript/",
    "cast_transcript_speakers/",
    "cast_videos/",
    "cast_voice_references/",
    "images/",
    "original_images/",
)

DEFAULT_MIN_AGE_HOURS = 24.0
# An upload writes its file to storage before the row that references it is
# committed. Deletion must leave that window alone, so it cannot be disabled.
SMALLEST_MIN_AGE_HOURS = 1.0

# Database backends on which writes of file references can be held off while
# one object is checked and deleted.
LOCKING_VENDORS = ("postgresql", "sqlite")
# How long to wait for the tables on PostgreSQL. Shorter than PostgreSQL's
# default deadlock_timeout (1s): when a request holds one of the tables and
# waits for another one, this command gives up and keeps the file instead of
# letting the deadlock detector pick a victim.
POSTGRESQL_LOCK_TIMEOUT_MS = 500


def normalize_media_path(path: str) -> str:
    return path.lstrip("/")


def reference_lock_statements(vendor: str, quoted_tables: list[str]) -> list[tuple[str, list[str]]]:
    """The statements that make the current transaction hold off writes to ``quoted_tables``."""
    if vendor == "postgresql":
        return [
            # The reference check has to see rows that are committed while this
            # transaction waits for the lock. Under REPEATABLE READ or
            # SERIALIZABLE it would read a snapshot instead, so the level is
            # set for this transaction whatever the connection's default is.
            # PostgreSQL only accepts this before the transaction's first
            # query: inside a transaction that already has a snapshot it
            # fails, and the file is kept. None of these statements is a
            # query, so the first snapshot is taken after the lock is held.
            ("SET TRANSACTION ISOLATION LEVEL READ COMMITTED", []),
            (f"SET LOCAL lock_timeout = '{POSTGRESQL_LOCK_TIMEOUT_MS}ms'", []),
            # SHARE conflicts with the ROW EXCLUSIVE lock that every INSERT,
            # UPDATE and DELETE takes, but not with reads. Waiting for it also
            # waits for every transaction that already wrote to a table.
            (f"LOCK TABLE {', '.join(quoted_tables)} IN SHARE MODE", []),
        ]
    # SQLite has one writer per database. A write statement, even one that
    # matches no row, makes this transaction that writer until it ends.
    return [(f"DELETE FROM {quoted_tables[0]} WHERE 1 = 0", [])]


class Command(BaseCommand):
    help = (
        "show media files which are in the production storage backend, but not in database and optionally delete them "
        "(requires production and backup storage backends configured)"
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--delete",
            action="store_true",
            dest="delete",
            default=False,
            help="Delete stale files instead of only showing them",
        )
        parser.add_argument(
            "--min-age-hours",
            type=float,
            dest="min_age_hours",
            default=DEFAULT_MIN_AGE_HOURS,
            help=(
                "With --delete, only delete stale files whose storage modification time is at least this many "
                f"hours old (default: {DEFAULT_MIN_AGE_HOURS:g}, minimum: {SMALLEST_MIN_AGE_HOURS:g}). "
                "Newer files may belong to an upload that is not committed yet."
            ),
        )

    @staticmethod
    def is_managed_media_path(path: str) -> bool:
        normalized_path = normalize_media_path(path)
        return any(normalized_path.startswith(prefix) for prefix in MANAGED_MEDIA_PREFIXES)

    @staticmethod
    def get_paths(storage: Storage) -> dict[str, int]:
        paths: dict[str, int] = {}
        for num, path in enumerate(storage_walk_paths(storage)):
            size = storage.size(path)
            paths[path] = size
            if num % 100 == 0:
                print(".", end="", flush=True)
            # print(path, size / 2 ** 20)
        return paths

    @staticmethod
    def iter_file_fields() -> Iterator[tuple[type[models.Model], models.FileField]]:
        """
        Every stored file column of every installed model.

        Not only django-cast's own models: Wagtail images and renditions, a
        custom image model, or a model of the site can all keep files under
        the managed prefixes, and any of those rows is a reference.
        """
        for model in apps.get_models():
            for field in model._meta.local_concrete_fields:
                if isinstance(field, models.FileField):
                    yield model, field

    @staticmethod
    def write_alias(model: type[models.Model]) -> str:
        """The database that holds the authoritative rows of ``model``, never a replica."""
        return router.db_for_write(model)

    def get_models_paths(self) -> set[str]:
        paths: set[str] = set()
        for model, field in self.iter_file_fields():
            # The base manager: a default manager may hide rows (drafts,
            # soft-deleted objects) whose files are still referenced.
            rows = model._base_manager.using(self.write_alias(model))
            for name in rows.values_list(field.attname, flat=True).iterator():
                if name:
                    paths.add(normalize_media_path(name))
        return paths

    def is_path_referenced(self, path: str) -> bool:
        """Ask the database now whether any row references ``path``."""
        normalized_path = normalize_media_path(path)
        names = {path, normalized_path, f"/{normalized_path}"}
        for model, field in self.iter_file_fields():
            rows = model._base_manager.using(self.write_alias(model))
            if rows.filter(**{f"{field.attname}__in": names}).exists():
                return True
        return False

    def get_reference_tables(self) -> dict[str, list[str]]:
        """The tables with file columns, by the database alias they are written to."""
        tables: dict[str, set[str]] = {}
        for model, _field in self.iter_file_fields():
            tables.setdefault(self.write_alias(model), set()).add(model._meta.db_table)
        return {alias: sorted(names) for alias, names in sorted(tables.items())}

    def check_reference_writes_can_be_blocked(self) -> None:
        for alias in self.get_reference_tables():
            vendor = connections[alias].vendor
            if vendor not in LOCKING_VENDORS:
                raise CommandError(
                    f"media_stale --delete cannot hold off writes of file references on the {vendor} database "
                    f"{alias!r} while it deletes, so it does not delete anything. Supported: "
                    f"{', '.join(LOCKING_VENDORS)}."
                )

    @contextmanager
    def reference_writes_blocked(self) -> Iterator[None]:
        """
        Hold off every write to a table with a file column.

        A reference check followed by a delete is only safe when no row can be
        committed in between. Inside this block every transaction that already
        wrote to one of the tables has finished, so its rows are visible, and
        no other transaction can write to them until the block is left.

        Raises ``DatabaseError`` when the tables cannot be locked in time.
        """
        with ExitStack() as stack:
            for alias, tables in self.get_reference_tables().items():
                connection = connections[alias]
                stack.enter_context(transaction.atomic(using=alias))
                quoted_tables = [connection.ops.quote_name(table) for table in tables]
                with connection.cursor() as cursor:
                    for sql, params in reference_lock_statements(connection.vendor, quoted_tables):
                        cursor.execute(sql, params)
            yield

    @staticmethod
    def get_age_retention_reason(storage: Storage, path: str, min_age: timedelta) -> str | None:
        """Why ``path`` is too new, or not provably old enough, to delete."""
        try:
            modified = storage.get_modified_time(path)
        except Exception as exc:
            return f"modification time unavailable ({exc.__class__.__name__})"
        if not isinstance(modified, datetime):
            return "modification time unavailable"
        now = timezone.now() if timezone.is_aware(modified) else datetime.now()
        if now - modified < min_age:
            return f"modified less than {min_age.total_seconds() / 3600:g} hours ago"
        return None

    def get_retention_reason(self, storage: Storage, path: str, min_age: timedelta) -> str | None:
        """
        Decide immediately before deleting ``path`` whether it has to stay.

        Must run inside ``reference_writes_blocked``. The reference snapshot
        taken for the report is stale by now, so the database is asked again.
        The age check comes last: a file written by an upload that has not
        written its row yet is invisible to the database check, but it is new.
        """
        if self.is_path_referenced(path):
            return "referenced by a database row"
        return self.get_age_retention_reason(storage, path, min_age)

    def delete_if_unreferenced(self, storage: Storage, path: str, min_age: timedelta) -> str | None:
        """
        Delete ``path`` unless it has to stay; return the reason when it stays.

        Check and delete happen while writes of file references are held off,
        so no row can start to reference the object between the two.
        """
        try:
            with self.reference_writes_blocked():
                reason = self.get_retention_reason(storage, path, min_age)
                if reason is None:
                    storage.delete(path)
                return reason
        except DatabaseError as exc:
            return f"file references could not be locked or checked ({exc.__class__.__name__})"

    def handle(self, *args: Any, **options: Any) -> None:
        min_age_hours = options["min_age_hours"]
        # ``not >=`` also rejects NaN
        if not min_age_hours >= SMALLEST_MIN_AGE_HOURS:
            raise CommandError(f"--min-age-hours must be at least {SMALLEST_MIN_AGE_HOURS:g}")
        min_age = timedelta(hours=min_age_hours)

        if options["delete"]:
            # before anything is listed, let alone deleted
            self.check_reference_writes_can_be_blocked()

        production_storage, _ = get_production_and_backup_storage()
        paths_from_models = self.get_models_paths()

        print("stale production")
        production_paths = self.get_paths(production_storage)
        stale_production: dict[str, int] = {}
        for path, size in production_paths.items():
            if not self.is_managed_media_path(path):
                continue
            if normalize_media_path(path) not in paths_from_models:
                print(path)
                stale_production[path] = size
        print(f"stale production size: {sum(stale_production.values()) / 2**20} Mb")

        if options["delete"]:
            deleted = 0
            retained = 0
            for path in stale_production.keys():
                reason = self.delete_if_unreferenced(production_storage, path, min_age)
                if reason is not None:
                    retained += 1
                    print(f"retained {path}: {reason}")
                    continue
                deleted += 1
                print(f"deleted {path}")
            print(f"deleted={deleted} retained={retained}")
