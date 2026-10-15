from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import QuerySet

from cast.models import Episode, Transcript
from cast.transcripts.corrections import refresh_transcript_corrections

from .import_transcript_glossary import Command as ImportGlossaryCommand


class Command(BaseCommand):
    help = (
        "Re-apply the transcript glossary: recompute automatic replacements and proposals from the raw "
        "transcript text with the current glossary, keep editor decisions, and rewrite the public files."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        selection = parser.add_mutually_exclusive_group(required=True)
        selection.add_argument(
            "--transcript", type=int, action="append", dest="transcripts", metavar="ID", help="Transcript id."
        )
        selection.add_argument("--podcast", help="Podcast page id or slug: transcripts of its episodes.")
        selection.add_argument("--all", action="store_true", help="All transcripts.")
        parser.add_argument("--dry-run", action="store_true", help="Report without writing.")

    @staticmethod
    def get_transcripts(options: dict[str, Any]) -> QuerySet[Transcript]:
        transcripts = Transcript.objects.select_related("audio").order_by("pk")
        if options["transcripts"]:
            return transcripts.filter(pk__in=options["transcripts"])
        if options["podcast"]:
            podcast = ImportGlossaryCommand.get_podcast(options["podcast"])
            episodes = Episode.objects.descendant_of(podcast)
            return transcripts.filter(audio__episodes__in=episodes).distinct()
        return transcripts.all()

    def handle(self, *args: Any, **options: Any) -> None:
        dry_run = options["dry_run"]
        failed = 0
        for transcript in self.get_transcripts(options):
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
