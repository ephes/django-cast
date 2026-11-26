from collections.abc import Iterable, Iterator
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser, OutputWrapper
from django.db import router
from django.db.models import QuerySet

from cast.models import Audio, Contributor, ContributorLink, Episode, EpisodeContributor, Transcript
from cast.transcripts.corrections import refresh_transcript_corrections

from ._selectors import positive_id
from .import_transcript_glossary import Command as ImportGlossaryCommand

ALL_BATCH_SIZE = 100


def _transcripts_at_start(transcripts: QuerySet[Transcript]) -> Iterator[Transcript]:
    """Read bounded pages on one database without holding a cursor during refresh."""
    transcripts = transcripts.using(transcripts.db)
    last_at_start = transcripts.order_by("-pk").values_list("pk", flat=True).first()
    if last_at_start is None:
        return
    # Keyset paging needs ascending primary keys, whatever the caller ordered by.
    admitted = transcripts.filter(pk__lte=last_at_start).order_by("pk")
    remaining = admitted
    while batch := list(remaining[:ALL_BATCH_SIZE]):
        yield from batch
        remaining = admitted.filter(pk__gt=batch[-1].pk)
        del batch


def _validate_transcript_database(transcript: Transcript) -> None:
    for operation in (router.db_for_read, router.db_for_write):
        if operation(Transcript, instance=transcript) != transcript._state.db:
            raise CommandError("Glossary application requires one database for transcript reads and writes.")


def _failure_status(exc: Exception) -> str:
    # Avoid formatting the exception or consulting a custom metaclass.
    error_type = type(exc)
    if type(error_type) is type:
        category = error_type.__name__
        if type(category) is str and len(category) <= 80 and category.isascii() and category.isidentifier():
            return f"failed ({category})"
    return "failed"


class Command(BaseCommand):
    help = (
        "Re-apply the transcript glossary: recompute automatic replacements and proposals from the raw "
        "transcript text with the current glossary, keep editor decisions, and rewrite the public files."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        selection = parser.add_mutually_exclusive_group(required=True)
        selection.add_argument(
            "--transcript", action="append", dest="transcripts", metavar="ID", help="Transcript id."
        )
        selection.add_argument("--podcast", help="Podcast page id or slug: transcripts of its episodes.")
        selection.add_argument("--all", action="store_true", help="All transcripts.")
        parser.add_argument("--dry-run", action="store_true", help="Report without writing.")

    @staticmethod
    def get_transcripts(options: dict[str, Any]) -> QuerySet[Transcript]:
        transcripts = Transcript.objects.select_related("audio").order_by("pk")
        if options["transcripts"]:
            ids = {positive_id(value, Transcript) for value in options["transcripts"]}
            selected = transcripts.filter(pk__in=ids)
            if set(selected.values_list("pk", flat=True)) != ids:
                raise CommandError("Unknown transcript ID in explicit selection.")
            return selected
        if options["podcast"]:
            podcast = ImportGlossaryCommand.get_podcast(options["podcast"])
            using = ImportGlossaryCommand.write_database(podcast)
            for model in (Episode, Transcript, Audio, Contributor, ContributorLink, EpisodeContributor):
                for operation in (router.db_for_read, router.db_for_write):
                    if operation(model, instance=podcast) != using:
                        raise CommandError(
                            "Glossary application requires one database for selection, reads and writes."
                        )
            episodes = Episode.objects.using(using).descendant_of(podcast)
            return transcripts.using(using).filter(audio__episodes__in=episodes).distinct()
        return transcripts.all()

    def handle(self, *args: Any, **options: Any) -> None:
        dry_run = options["dry_run"]
        completed = changed = failed = 0

        def report(stream: OutputWrapper, message: str) -> None:
            try:
                stream.write(message)
                stream.flush()
            except Exception:
                raise CommandError(
                    f"Glossary receipt failed: completed={completed} changed={changed} failed={failed} dry_run={dry_run}"
                ) from None

        transcripts = self.get_transcripts(options)
        selected: Iterable[Transcript]
        archive = options["all"]
        if not archive:
            selected = list(transcripts)
            # Validate every actual transcript before refreshing the first one.
            # Instance-sensitive routers may differ from the podcast preflight.
            for transcript in selected:
                _validate_transcript_database(transcript)
        else:
            selected = _transcripts_at_start(transcripts)
        for transcript in selected:
            try:
                if archive:
                    _validate_transcript_database(transcript)
                result = refresh_transcript_corrections(transcript, dry_run=dry_run)
            except Exception as exc:
                failed += 1
                stream = self.stderr
                receipt = f"transcript {transcript.pk}: {_failure_status(exc)}"
            else:
                changed += bool(result.changed or result.format_changes.dote or result.format_changes.vtt)
                stream = self.stdout
                receipt = (
                    f"transcript {transcript.pk}: {result.status} automatic={result.automatic} "
                    f"approved={result.approved} proposals={result.proposals} changed={result.changed} "
                    f"dote_changed={result.format_changes.dote} vtt_changed={result.format_changes.vtt}"
                )
            completed += 1
            report(stream, receipt)
        if dry_run:
            report(self.stdout, "dry run, nothing written")
        if failed:
            raise CommandError(f"{failed} transcript(s) failed")
