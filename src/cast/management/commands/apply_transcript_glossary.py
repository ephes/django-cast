from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import router
from django.db.models import QuerySet

from cast.models import Audio, Contributor, ContributorLink, Episode, EpisodeContributor, Transcript
from cast.transcripts.corrections import refresh_transcript_corrections

from ._selectors import positive_id
from .import_transcript_glossary import Command as ImportGlossaryCommand


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
        failed = 0
        transcripts = self.get_transcripts(options)
        selected = list(transcripts)
        if options["podcast"]:
            # Validate every actual transcript before refreshing the first one.
            # Instance-sensitive routers may differ from the podcast preflight.
            for transcript in selected:
                for operation in (router.db_for_read, router.db_for_write):
                    if operation(Transcript, instance=transcript) != transcript._state.db:
                        raise CommandError(
                            "Glossary application requires one database for transcript reads and writes."
                        )
        for transcript in selected:
            try:
                result = refresh_transcript_corrections(transcript, dry_run=dry_run)
            except Exception as exc:
                failed += 1
                self.stderr.write(f"transcript {transcript.pk}: failed: {exc}")
                continue
            self.stdout.write(
                f"transcript {transcript.pk}: {result.status} automatic={result.automatic} "
                f"approved={result.approved} proposals={result.proposals} changed={result.changed}"
            )
        if dry_run:
            self.stdout.write("dry run, nothing written")
        if failed:
            raise CommandError(f"{failed} transcript(s) failed")
