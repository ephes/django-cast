from collections.abc import Iterator
from typing import Any, TextIO, cast

from django.core.management.base import BaseCommand, CommandError, OutputWrapper
from django.db import router
from django.db.models import Count, Max, QuerySet
from rich.console import Console
from rich.progress import track

from ...models import Video

VIDEO_BATCH_SIZE = 200


def _video_pages(videos: QuerySet[Video], last_at_start: int | None) -> Iterator[Video]:
    """Enumerate a bounded PK range with no query cursor open during publication."""
    if last_at_start is None:
        return
    admitted = videos.filter(pk__lte=last_at_start)
    remaining = admitted
    while page := list(remaining[:VIDEO_BATCH_SIZE]):
        yield from page
        remaining = admitted.filter(pk__gt=page[-1].pk)
        del page


class _ProgressConsole(Console):
    def on_broken_pipe(self) -> None:
        # Keep the progress failure in the command's error path instead of exiting Rich.
        self.quiet = True
        raise BrokenPipeError


class Command(BaseCommand):
    help = "recalc the poster images for videos from the videos"

    def handle(self, *args: Any, **options: Any) -> None:
        processed = errors = 0

        def report(stream: OutputWrapper, message: str, receipt: str) -> None:
            try:
                stream.write(message)
                stream.flush()
            except Exception:
                raise CommandError(
                    f"Poster backfill {receipt} failed: processed={processed} errors={errors}"
                ) from None

        using = router.db_for_write(Video)
        videos = Video.objects.using(using).order_by("pk")
        scope = videos.aggregate(last_pk=Max("pk"), total=Count("pk"))
        # Django registers OutputWrapper as a text stream and delegates its I/O methods.
        console = _ProgressConsole(file=cast(TextIO, self.stdout))
        try:
            for video in track(
                _video_pages(videos, scope["last_pk"]),
                total=scope["total"],
                description="Recalculating video posters",
                console=console,
                disable=not self.stdout.isatty(),
                auto_refresh=False,
            ):
                processed += 1
                try:
                    video.publish_missing_poster()
                except Exception:
                    errors += 1
                    report(
                        self.stderr,
                        f"error recalculating poster for video {video.pk}: generation/publication failed",
                        "diagnostic",
                    )
        except OSError:
            raise CommandError(f"Poster backfill progress failed: processed={processed} errors={errors}") from None

        report(self.stdout, f"processed={processed} errors={errors}", "summary")
        if errors:
            raise CommandError(f"{errors} of {processed} video posters could not be recalculated")
