from __future__ import annotations

from argparse import ArgumentParser
from dataclasses import dataclass
from uuid import uuid4

from django.core.exceptions import ObjectDoesNotExist
from django.core.management.base import BaseCommand, CommandError

from ...models import Audio, Episode
from ...voxhelm import VoxhelmError, VoxhelmTranscriptService, transcript_complete


@dataclass(frozen=True)
class TranscriptTarget:
    audio: Audio
    episode: Episode | None = None


class Command(BaseCommand):
    help = "Generate transcript artifacts for specific episodes or audio objects using Voxhelm."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--episode-id",
            action="append",
            default=[],
            type=int,
            help="Episode id to transcribe. Can be passed more than once.",
        )
        parser.add_argument(
            "--audio-id",
            action="append",
            default=[],
            type=int,
            help="Audio id to transcribe directly. Can be passed more than once.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Regenerate transcripts even when all transcript files already exist.",
        )

    def handle(self, *args, **options) -> None:
        episode_ids = list(options["episode_id"])
        audio_ids = list(options["audio_id"])
        if not episode_ids and not audio_ids:
            raise CommandError("Provide at least one --episode-id or --audio-id.")

        targets = self._resolve_targets(episode_ids=episode_ids, audio_ids=audio_ids)
        service = VoxhelmTranscriptService()
        created = 0
        updated = 0
        skipped = 0
        errors = 0

        for target in targets:
            audio = target.audio
            existing = self._get_existing_transcript(audio=audio)
            if existing is not None and transcript_complete(existing) and not options["force"]:
                skipped += 1
                self.stdout.write(f"skipped audio={audio.pk} transcript={existing.pk}")
                continue

            task_ref = f"cast-audio-{audio.pk}"
            if options["force"]:
                task_ref = f"{task_ref}-{uuid4().hex[:8]}"

            try:
                result = service.generate_for_audio(audio, task_ref=task_ref, episode=target.episode)
            except VoxhelmError as exc:
                errors += 1
                self.stderr.write(f"error audio={audio.pk}: {exc}")
                continue

            if result.created:
                created += 1
                action = "created"
            else:
                updated += 1
                action = "updated"
            self.stdout.write(f"{action} audio={audio.pk} transcript={result.transcript.pk} job={result.job_id}")

        self.stdout.write(
            f"processed={len(targets)} created={created} updated={updated} skipped={skipped} errors={errors}"
        )
        if errors:
            raise CommandError(f"{errors} transcript generations failed.")

    @staticmethod
    def _get_existing_transcript(*, audio: Audio):
        try:
            return audio.transcript
        except ObjectDoesNotExist:
            return None

    def _resolve_targets(self, *, episode_ids: list[int], audio_ids: list[int]) -> list[TranscriptTarget]:
        targets: list[TranscriptTarget] = []
        seen_audio_ids: set[int] = set()

        episodes = list(
            Episode.objects.filter(pk__in=episode_ids).select_related("podcast_audio__transcript").order_by("pk")
        )
        found_episode_ids = {episode.pk for episode in episodes}
        missing_episode_ids = sorted(set(episode_ids).difference(found_episode_ids))
        if missing_episode_ids:
            missing = ", ".join(str(episode_id) for episode_id in missing_episode_ids)
            raise CommandError(f"Unknown episode id(s): {missing}")
        for episode in episodes:
            if episode.podcast_audio_id is None:
                raise CommandError(f"Episode {episode.pk} has no podcast audio.")
            audio = episode.podcast_audio
            if audio.pk is None or audio.pk in seen_audio_ids:
                continue
            targets.append(TranscriptTarget(audio=audio, episode=episode))
            seen_audio_ids.add(audio.pk)

        direct_audios = list(Audio.objects.filter(pk__in=audio_ids).select_related("transcript").order_by("pk"))
        found_audio_ids = {audio.pk for audio in direct_audios}
        missing_audio_ids = sorted(set(audio_ids).difference(found_audio_ids))
        if missing_audio_ids:
            missing = ", ".join(str(audio_id) for audio_id in missing_audio_ids)
            raise CommandError(f"Unknown audio id(s): {missing}")
        for audio in direct_audios:
            if audio.pk is None or audio.pk in seen_audio_ids:
                continue
            targets.append(TranscriptTarget(audio=audio))
            seen_audio_ids.add(audio.pk)

        return targets
