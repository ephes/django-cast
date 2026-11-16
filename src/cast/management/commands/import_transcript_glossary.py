import json
import os
import stat
from copy import copy
from typing import Any

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import IntegrityError, connections, router, transaction
from django.db.models import F, Value
from django.db.models.functions import Lower
from django.utils import timezone
from wagtail.models import Locale, Page, Site

from cast.models import Podcast, TranscriptGlossaryTerm, VoxhelmSettings
from cast.models.transcript_glossary import GlossaryValidationContext
from cast.transcripts.glossary import normalize_phrase

from ._selectors import is_id_selector, positive_id

MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_ENTRIES = 10_000


def _unique_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CommandError("Glossary input contains a duplicate JSON member.")
        result[key] = value
    return result


def _variants_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return "\n".join(value)
    raise ValueError('"variants" must be a string or a list of strings')


def _validation_message(error: ValidationError) -> str:
    return "; ".join(f"{field}: {' '.join(messages)}" for field, messages in error.message_dict.items())


class Command(BaseCommand):
    help = (
        "Import transcript glossary terms for one podcast from a JSON file: a list of objects with "
        '"term", optional "variants" (list or newline-separated string) and optional "notes". '
        "Terms are matched case-insensitively; existing terms are updated."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("podcast", help="Podcast page id or slug.")
        parser.add_argument("json_file", help="Path to the JSON file.")
        parser.add_argument("--dry-run", action="store_true", help="Validate and report without saving.")

    @staticmethod
    def get_podcast(identifier: str) -> Podcast:
        using = router.db_for_write(Podcast)
        if using not in connections:
            raise CommandError("Glossary import selected an unknown database.")
        if is_id_selector(identifier):
            podcast = Podcast.objects.using(using).filter(pk=positive_id(identifier, Podcast)).first()
            if podcast is None:
                raise CommandError(f"No podcast with id {identifier}.")
            return podcast
        podcasts = list(Podcast.objects.using(using).filter(slug=identifier))
        if not podcasts:
            raise CommandError(f'No podcast with slug "{identifier}".')
        if len(podcasts) > 1:
            ids = ", ".join(str(podcast.pk) for podcast in podcasts)
            raise CommandError(f'Several podcasts have the slug "{identifier}" (ids {ids}); pass the id.')
        return podcasts[0]

    @staticmethod
    def load_entries(path: str) -> list[Any]:
        try:
            # Follow symlinks intentionally, but admit the opened target before reading.
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise CommandError("Glossary input must be a regular file.")
                with os.fdopen(fd, "rb", closefd=False) as source:
                    raw = source.read(MAX_INPUT_BYTES + 1)
            finally:
                os.close(fd)
        except OSError as exc:
            raise CommandError(f"Cannot read {path}: {exc.strerror or 'unreadable file'}.") from exc
        if len(raw) > MAX_INPUT_BYTES:
            raise CommandError(f"Glossary input exceeds {MAX_INPUT_BYTES} bytes.")
        try:
            data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_members)
        except json.JSONDecodeError as exc:
            raise CommandError(f"Cannot read {path}: invalid JSON at line {exc.lineno}, column {exc.colno}.") from exc
        except (UnicodeDecodeError, RecursionError) as exc:
            raise CommandError(f"Cannot read {path}: invalid UTF-8 JSON.") from exc
        if not isinstance(data, list):
            raise CommandError(f"{path} must contain a JSON list of glossary entries.")
        if len(data) > MAX_ENTRIES:
            raise CommandError(f"Glossary input exceeds {MAX_ENTRIES} entries.")
        return data

    def handle(self, *args: Any, **options: Any) -> None:
        podcast = self.get_podcast(options["podcast"])
        using = self.write_database(podcast)
        entries = self.load_entries(options["json_file"])
        dry_run = options["dry_run"]
        counts = {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0}
        seen: dict[str, int] = {}
        with transaction.atomic(using=using):
            # Share the stable parent-row lock used by transcript review and
            # snippet saves. Lock before reading any cross-term variant state.
            Page.objects.using(using).filter(pk=podcast.pk).update(title=F("title"))
            context = GlossaryValidationContext.for_podcast(podcast, ())
            existing = self.existing_terms(podcast, context)
            for number, entry in enumerate(entries, start=1):
                outcome, reason = self.import_entry(podcast, entry, number, seen, existing, context)
                counts[outcome] += 1
                if reason:
                    self.stderr.write(f"skipped entry {number}: {reason}")
            if dry_run:
                transaction.set_rollback(True, using=using)
        summary = " ".join(f"{name}={count}" for name, count in counts.items())
        suffix = " (dry run, nothing saved)" if dry_run else ""
        self.stdout.write(f"{podcast.title}: {summary}{suffix}")

    @staticmethod
    def write_database(podcast: Podcast, instance: TranscriptGlossaryTerm | None = None) -> str:
        using = podcast._state.db
        for model in (Page, Podcast, TranscriptGlossaryTerm):
            for operation in (router.db_for_read, router.db_for_write):
                if operation(model, instance=instance if instance is not None else podcast) != using:
                    raise CommandError(
                        "Glossary import requires one database for reads, validation, locks and writes."
                    )
        if any(router.db_for_read(model, instance=podcast) != using for model in (Site, Locale, VoxhelmSettings)):
            raise CommandError("Glossary language validation requires the same database as the import.")
        assert using is not None
        return using

    @staticmethod
    def existing_terms(
        podcast: Podcast, validation_context: GlossaryValidationContext | None = None
    ) -> dict[str, TranscriptGlossaryTerm]:
        existing = {}
        for term in TranscriptGlossaryTerm.objects.using(podcast._state.db).filter(podcast=podcast):
            # Index every row for validation, even when normalized identities
            # collide and the import's update lookup selects the last row.
            if validation_context is not None:
                validation_context.accept(term)
            existing[normalize_phrase(term.term)] = term
        return existing

    @staticmethod
    def import_entry(
        podcast: Podcast,
        entry: Any,
        number: int,
        seen: dict[str, int],
        existing: dict[str, TranscriptGlossaryTerm],
        validation_context: GlossaryValidationContext,
    ) -> tuple[str, str]:
        """Create or update one term; return the outcome and, for skipped entries, the reason."""
        if not isinstance(entry, dict):
            return "skipped", "an entry must be an object"
        term = entry.get("term")
        if not isinstance(term, str) or not term.strip():
            return "skipped", '"term" must be a non-empty string'
        label = f'"{term.strip()}"'
        notes = entry.get("notes", None)
        if notes is not None and not isinstance(notes, str):
            return "skipped", f'{label}: "notes" must be a string'
        try:
            variants = _variants_text(entry["variants"]) if "variants" in entry else None
        except ValueError as exc:
            return "skipped", f"{label}: {exc}"
        key = normalize_phrase(term)
        if key in seen:
            return "skipped", f"{label}: duplicate of entry {seen[key]}"
        seen[key] = number

        instance = copy(existing[key]) if key in existing else None
        created = instance is None
        if instance is None:
            instance = TranscriptGlossaryTerm(podcast=podcast)
            before = None
        else:
            before = (instance.term, instance.variants, instance.notes)
        instance.term = term.strip()
        if variants is not None:
            instance.variants = variants
        if notes is not None:
            instance.notes = notes
        using = Command.write_database(podcast, instance)
        conflict = f"{label}: concurrent edit; reload and retry this entry"
        try:
            instance.full_clean(validation_context=validation_context)
        except ValidationError as exc:
            if (
                created
                and TranscriptGlossaryTerm.objects.using(using)
                .filter(podcast=podcast)
                .alias(import_term_lower=Lower("term"))
                .filter(import_term_lower=Lower(Value(instance.term)))
                .exists()
            ):
                return "skipped", conflict
            return "skipped", f"{label}: {_validation_message(exc)}"
        if before == (instance.term, instance.variants, instance.notes):
            return "unchanged", ""
        if created:
            try:
                with transaction.atomic(using=using):
                    instance.save(using=using)
            except IntegrityError:
                return "skipped", conflict
        else:
            fields = ["term"]
            if variants is not None:
                fields.append("variants")
            if notes is not None:
                fields.append("notes")
            expected = {field: getattr(existing[key], field) for field in fields}
            updates = {field: getattr(instance, field) for field in fields}
            # Compare and publish in one statement. Omitted fields never enter the
            # UPDATE, and an edit to an owned field since lookup is a conflict.
            if (
                not TranscriptGlossaryTerm.objects.using(using)
                .filter(pk=instance.pk, podcast_id=podcast.pk, **expected)
                .update(**updates, modified=timezone.now())
            ):
                return "skipped", conflict
        existing[key] = instance
        validation_context.accept(instance)
        return ("created" if created else "updated"), ""
