import json
from pathlib import Path
from typing import Any

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from cast.models import Podcast, TranscriptGlossaryTerm
from cast.transcripts.glossary import normalize_phrase


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
        if identifier.isdigit():
            podcast = Podcast.objects.filter(pk=int(identifier)).first()
            if podcast is None:
                raise CommandError(f"No podcast with id {identifier}.")
            return podcast
        podcasts = list(Podcast.objects.filter(slug=identifier))
        if not podcasts:
            raise CommandError(f'No podcast with slug "{identifier}".')
        if len(podcasts) > 1:
            ids = ", ".join(str(podcast.pk) for podcast in podcasts)
            raise CommandError(f'Several podcasts have the slug "{identifier}" (ids {ids}); pass the id.')
        return podcasts[0]

    @staticmethod
    def load_entries(path: str) -> list[Any]:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CommandError(f"Cannot read {path}: {exc}") from exc
        if not isinstance(data, list):
            raise CommandError(f"{path} must contain a JSON list of glossary entries.")
        return data

    def handle(self, *args: Any, **options: Any) -> None:
        podcast = self.get_podcast(options["podcast"])
        entries = self.load_entries(options["json_file"])
        dry_run = options["dry_run"]
        counts = {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0}
        seen: dict[str, int] = {}
        with transaction.atomic():
            for number, entry in enumerate(entries, start=1):
                outcome, reason = self.import_entry(podcast, entry, number, seen)
                counts[outcome] += 1
                if reason:
                    self.stderr.write(f"skipped entry {number}: {reason}")
            if dry_run:
                transaction.set_rollback(True)
        summary = " ".join(f"{name}={count}" for name, count in counts.items())
        suffix = " (dry run, nothing saved)" if dry_run else ""
        self.stdout.write(f"{podcast.title}: {summary}{suffix}")

    @staticmethod
    def import_entry(podcast: Podcast, entry: Any, number: int, seen: dict[str, int]) -> tuple[str, str]:
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

        existing = {
            normalize_phrase(glossary_term.term): glossary_term
            for glossary_term in TranscriptGlossaryTerm.objects.filter(podcast=podcast)
        }
        instance = existing.get(key)
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
        try:
            instance.full_clean()
        except ValidationError as exc:
            return "skipped", f"{label}: {_validation_message(exc)}"
        if before == (instance.term, instance.variants, instance.notes):
            return "unchanged", ""
        instance.save()
        return ("created" if created else "updated"), ""
