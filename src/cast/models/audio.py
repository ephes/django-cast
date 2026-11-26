import json
import logging
import re
import subprocess
from collections.abc import Iterable
from copy import deepcopy
from datetime import time, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Protocol

from django.contrib.auth import get_user_model
from django.core.files.storage import Storage
from django.db import models, router, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel
from taggit.managers import TaggableManager
from wagtail.models import CollectionMember, PageManager
from wagtail.search import index
from wagtail.search.queryset import SearchableQuerySetMixin

from ..media_probe import input_protocol_args, is_http_media_url, run_media_probe

if TYPE_CHECKING:
    from .pages import Episode

logger = logging.getLogger(__name__)

_SAVE_OPTION_UNSET = object()


def format_chapter_start(start: time) -> str:
    """Format an elapsed chapter start without losing stored precision."""
    if not start.microsecond:
        return start.isoformat(timespec="seconds")
    if start.microsecond % 1000 == 0:
        return start.isoformat(timespec="milliseconds")
    return start.isoformat(timespec="microseconds")


class AudioDurationProbeError(Exception):
    """Raised when required audio duration probing fails."""


class AudioDurationProbeTimeout(AudioDurationProbeError):
    """Raised when required audio duration probing exceeds its timeout/budget."""


class AudioQuerySet(SearchableQuerySetMixin, models.QuerySet):
    pass


class FileField(Protocol):
    """Just to make mypy happy about field.url and field.path"""

    file: object
    name: str
    storage: Storage
    url: str
    path: str


class Audio(CollectionMember, index.Indexed, TimeStampedModel):  # type: ignore[django-manager-missing]
    """Represents an audio file with support for multiple formats (MP3, M4A, OGA, OPUS).

    Provides automatic duration detection via FFprobe, chapter mark associations,
    transcript linking, and Podlove Web Player integration for podcast episodes.
    """

    class TranscriptDiarizationMode(models.TextChoices):
        INHERIT = "inherit", _("Inherit")
        ENABLED = "enabled", _("Enabled")
        DISABLED = "disabled", _("Disabled")

    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
    duration = models.DurationField(null=True, blank=True)
    title = models.CharField(max_length=255, null=True, blank=True)
    subtitle = models.CharField(max_length=512, null=True, blank=True)
    transcript_diarization_mode = models.CharField(
        max_length=16,
        choices=TranscriptDiarizationMode.choices,
        default=TranscriptDiarizationMode.INHERIT,
        help_text=_(
            "Controls speaker diarization for transcript generation and public speaker-label display for this "
            "audio. Disabling keeps transcript text and timestamps, hides any stored speaker labels publicly, and "
            "future generations will not request speaker diarization. This audio transcript may be shared by "
            "multiple episodes."
        ),
    )

    m4a = models.FileField(upload_to="cast_audio/", null=True, blank=True)
    mp3 = models.FileField(upload_to="cast_audio/", null=True, blank=True)
    oga = models.FileField(upload_to="cast_audio/", null=True, blank=True)
    opus = models.FileField(upload_to="cast_audio/", null=True, blank=True)

    data = models.JSONField("Metadata", blank=True, default=dict)

    mime_lookup: dict[str, str] = {
        "mp3": "audio/mpeg",
        "m4a": "audio/mp4",
        "oga": "audio/ogg",
        "opus": "audio/opus",
    }
    audio_formats: list[str] = list(mime_lookup.keys())
    title_lookup: dict[str, str] = {key: f"Audio {key.upper()}" for key in audio_formats}

    admin_form_fields: tuple[str, ...] = (
        "title",
        "subtitle",
        "transcript_diarization_mode",
        "m4a",
        "mp3",
        "oga",
        "opus",
        "tags",
    )

    search_fields = CollectionMember.search_fields + [
        index.SearchField("title", partial_match=True, boost=10),
        index.RelatedFields(
            "tags",
            [
                index.SearchField("title", partial_match=True, boost=10),
                index.SearchField("subtitle", partial_match=True, boost=5),
            ],
        ),
        index.FilterField("user"),
    ]

    objects: PageManager["Audio"] = AudioQuerySet.as_manager()
    episodes: models.QuerySet["Episode"]  # mypy needs this
    tags = TaggableManager(help_text=None, blank=True, verbose_name=_("tags"))

    class Meta:
        ordering = ("-created",)
        permissions = (("choose_audio", "Can choose audio"),)

    @property
    def uploaded_audio_files(self) -> Iterable[tuple[str, FileField]]:
        for name in self.audio_formats:
            field = getattr(self, name)
            if field.name is not None and len(field.name) > 0:
                yield name, field

    @property
    def file_formats(self) -> str:
        return " ".join([n for n, f in self.uploaded_audio_files])

    def get_audio_file_names(self) -> set[str]:
        audio_file_names = set()
        for audio_format, field in self.uploaded_audio_files:
            audio_file_names.add(Path(field.name).stem)
        return audio_file_names

    @property
    def name(self) -> str:
        if self.title is not None:
            return self.title
        return ",".join([_ for _ in self.get_audio_file_names()])

    def __str__(self) -> str:
        return f"{self.pk} - {self.name}"

    def get_all_paths(self) -> set[str]:
        paths = set()
        for name, field in self.uploaded_audio_files:
            paths.add(field.name)
        return paths

    @staticmethod
    def _get_audio_duration(audio_url: str | Path) -> timedelta:
        # Taken from: http://trac.ffmpeg.org/wiki/FFprobeTips
        cmd = [
            "ffprobe",
            "-v",
            "0",
            "-print_format",
            "json",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            *input_protocol_args(audio_url),
            str(audio_url),
        ]
        result = run_media_probe(cmd, timeout=30).stdout.decode().strip()
        if re.fullmatch(r"[0-9]+\.[0-9]+", result) is None:
            raise ValueError(f"Could not parse duration: {result}")
        seconds = Decimal(result)
        if seconds > Decimal("9223372036854.775807"):
            raise ValueError("Audio duration exceeds signed 64-bit microsecond storage")
        with localcontext() as context:
            context.prec = 30
            rounded = seconds.quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN)
            return timedelta(microseconds=int(rounded * 1_000_000))

    def create_duration(self) -> None:
        for _name, field in self.uploaded_audio_files:
            try:
                url = getattr(field, "url", None)
                if url is None:
                    continue
                audio_source = url if is_http_media_url(url) else getattr(field, "path", None)
                if audio_source is not None:
                    self.duration = self._get_audio_duration(audio_source)
                    break
            except NotImplementedError:
                continue
            except subprocess.TimeoutExpired as exc:
                raise AudioDurationProbeTimeout("Audio duration probing timed out.") from exc
            except (subprocess.CalledProcessError, OSError, ValueError) as exc:
                raise AudioDurationProbeError("Audio duration probing failed.") from exc

    @property
    def audio(self) -> list[dict[str, str]]:
        items = []
        for name, field in self.uploaded_audio_files:
            if not hasattr(field, "url"):
                continue
            items.append(
                {
                    "url": field.url,  # type: ignore
                    "mimeType": self.mime_lookup[name],
                    "size": str(self.get_file_size(name)),
                    "title": str(self.title_lookup[name]),
                }
            )
        return items

    def _ordered_chaptermarks(self) -> list["ChapterMark"]:
        return sorted(self.chaptermarks.all(), key=lambda mark: mark.start)

    @property
    def chapters(self) -> list[dict[str, str | None]]:
        items = []
        # chapter marks have to be ordered by start for
        # podlove web player - dunno why, 2019-04-19 jochen
        for chapter in self._ordered_chaptermarks():
            items.append(
                {
                    "start": format_chapter_start(chapter.start),
                    "title": chapter.title,
                    "href": chapter.link,  # could be None
                    "image": chapter.image,  # could be None
                }
            )
        return items

    @property
    def chapters_as_text(self) -> str:
        chaptermarks = []
        for mark in self._ordered_chaptermarks():
            chaptermarks.append(f"{mark.start} {mark.title}")
        return "\n".join(chaptermarks)

    @staticmethod
    def clean_ffprobe_chaptermarks(ffprobe_data: object) -> list[dict[str, str]]:
        cleaned: list[dict[str, str]] = []
        if not isinstance(ffprobe_data, dict):
            return cleaned
        chapters = ffprobe_data.get("chapters", [])
        if not isinstance(chapters, list):
            return cleaned
        for item in chapters:
            if not isinstance(item, dict):
                continue
            start = item.get("start_time")
            tags = item.get("tags", {})
            title = tags.get("title") if isinstance(tags, dict) else None
            if not isinstance(start, str) or not isinstance(title, str):
                continue
            title = title.strip()
            if not title:
                continue
            cleaned.append({"start": start, "title": title})
        return cleaned

    def get_chaptermark_data_from_file(self, audio_format: str) -> list[dict[str, str]]:
        file_field = getattr(self, audio_format)
        try:
            url = file_field.url
        except ValueError:
            return []
        if not is_http_media_url(url):
            # use path from local filesystem
            url = file_field.path
        command = [
            "ffprobe",
            *input_protocol_args(url),
            "-i",
            str(url),
            "-print_format",
            "json",
            "-show_chapters",
            "-loglevel",
            "error",
        ]
        ffprobe_data = json.loads(run_media_probe(command).stdout)
        return self.clean_ffprobe_chaptermarks(ffprobe_data)

    def set_episode_id(self, episode_id: int) -> None:
        """Set the episode id for this audio file to be able to return audio.episode_url in api."""
        self._episode_id = episode_id

    def get_episode(self, episode_id: int | None = None) -> Optional["Episode"]:
        episodes = self.episodes.all()
        if episode_id is not None:
            episodes = episodes.filter(pk=episode_id)
        episodes = list(episodes)  # type: ignore
        if len(episodes) == 1:
            return episodes[0]
        return None

    @property
    def episode_url(self) -> str | None:
        """Return the url to the episode this audio file belongs to."""
        episode_id = None
        if hasattr(self, "_episode_id"):
            episode_id = self._episode_id
        episode = self.get_episode(episode_id)
        if episode is not None:
            return episode.full_url
        return None

    def get_podlove_url(self, post_pk: int) -> str:
        return reverse("cast:api:audio_podlove_detail", kwargs={"pk": self.pk, "post_id": post_pk})

    @property
    def duration_str(self) -> str:
        if self.duration is None:
            return ""
        # Total hours, never "1 day, ..." -- itunes:duration needs H:MM:SS.
        total_seconds = int(self.duration.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours}:{minutes:02d}:{seconds:02d}"

    def size_to_metadata(self) -> None:
        sizes = self.data.setdefault("size", {})
        names = self.data.setdefault("size_file_names", {})
        for audio_format in self.audio_formats:
            sizes.pop(audio_format, None)
            names.pop(audio_format, None)
            field = getattr(self, audio_format)
            if not field:
                continue
            try:
                sizes[audio_format] = field.size
                names[audio_format] = field.name
            except (OSError, ValueError):
                # Missing/unreadable current files must retire their previous size.
                pass

    def refresh_file_size_cache(self, *, using: str | None = None) -> bool:
        """Probe file sizes and merge only the probed size keys into the stored row.

        Storage is probed before the row lock. Under the lock, only formats whose
        stored file name still equals the probed name get new size keys; titles,
        replaced files and other metadata saved meanwhile are left untouched.
        Returns whether the stored metadata changed.
        """
        probes: dict[str, tuple[str, int | None]] = {}
        for audio_format in self.audio_formats:
            field = getattr(self, audio_format)
            size: int | None = None
            if field:
                try:
                    size = field.size
                except (OSError, ValueError):
                    # Missing/unreadable current files must retire their previous size.
                    size = None
            probes[audio_format] = (field.name or "" if field else "", size)
        using = using or router.db_for_write(Audio, instance=self)
        with transaction.atomic(using=using):
            rows = Audio.objects.using(using).filter(pk=self.pk)
            # Lock the row before reading, like ChapterMarkManager.sync_chaptermarks.
            if not rows.update(title=models.F("title")):
                raise Audio.DoesNotExist
            current = rows.values(*self.audio_formats, "data").get()
            stored_data = current["data"] if isinstance(current["data"], dict) else {}
            data = deepcopy(stored_data)
            sizes = data.setdefault("size", {})
            names = data.setdefault("size_file_names", {})
            for audio_format, (name, size) in probes.items():
                if (current[audio_format] or "") != name:
                    continue  # replaced meanwhile; the replacing save owns that size
                sizes.pop(audio_format, None)
                names.pop(audio_format, None)
                if name and size is not None:
                    sizes[audio_format] = size
                    names[audio_format] = name
            changed = data != stored_data
            if changed:
                rows.update(data=data, modified=timezone.now())
        self.data = data
        return changed

    def get_file_size(self, audio_format: str) -> int:
        """Return a size bound to the current file name, without I/O on a cache hit."""
        file_field = getattr(self, audio_format)
        if not file_field:
            return 0
        cached_size = self.data.get("size", {}).get(audio_format)
        cached_name = self.data.get("size_file_names", {}).get(audio_format)
        if cached_size is not None and cached_name == file_field.name:
            return cached_size
        try:
            return file_field.size
        except (OSError, ValueError):
            return 0

    def save(self, *args: Any, **kwargs: Any) -> None:
        duration = kwargs.pop("duration", _SAVE_OPTION_UNSET)
        cache_file_sizes = kwargs.pop("cache_file_sizes", _SAVE_OPTION_UNSET)
        if duration is not _SAVE_OPTION_UNSET or cache_file_sizes is not _SAVE_OPTION_UNSET:
            generate_duration = True if duration is _SAVE_OPTION_UNSET else bool(duration)
            should_cache_file_sizes = True if cache_file_sizes is _SAVE_OPTION_UNSET else bool(cache_file_sizes)
            if not generate_duration and not should_cache_file_sizes:
                super().save(*args, **kwargs)
                return
            from cast.media_derivation import save_audio_with_derivations

            save_audio_with_derivations(
                self,
                *args,
                generate_duration=generate_duration,
                cache_file_sizes=should_cache_file_sizes,
                **kwargs,
            )
            return
        super().save(*args, **kwargs)


def sync_chapter_marks(
    from_database: list["ChapterMark"], from_cms: list["ChapterMark"]
) -> tuple[list["ChapterMark"], list["ChapterMark"], list["ChapterMark"]]:
    start_from_database = {cm.start: cm for cm in from_database}
    start_from_cms = {cm.start for cm in from_cms}
    to_add, to_update = [], []
    for cm in from_cms:
        if cm.start not in start_from_database:
            to_add.append(cm)
        else:
            cm_from_db = start_from_database[cm.start]
            if cm.has_changed(cm_from_db):
                # A separate instance keeps the stored pk off the caller's input.
                to_update.append(
                    ChapterMark(
                        pk=cm_from_db.pk,
                        audio_id=cm.audio_id,
                        start=cm.start,
                        title=cm.title,
                        link=cm.link,
                        image=cm.image,
                    )
                )
    to_remove = [cm for cm in from_database if cm.start not in start_from_cms]
    return to_add, to_update, to_remove


class ChapterMarkManager(models.Manager):
    @staticmethod
    def sync_chaptermarks(
        audio: Audio, from_cms: list["ChapterMark"], *, update_urls: bool = True, using: str | None = None
    ) -> None:
        # Persist separate instances: a rolled-back write must not leave pks,
        # normalized starts or stored URLs on the caller's (retryable) inputs.
        start_field = ChapterMark._meta.get_field("start")
        pending: list[ChapterMark] = []
        starts = set()
        for cm in from_cms:
            if cm.audio_id != audio.pk:
                raise ValueError("Chapter marks must belong to the synchronized audio")
            start = start_field.to_python(cm.start)
            if start in starts:
                raise ValueError("Duplicate chapter start")
            starts.add(start)
            pending.append(ChapterMark(audio_id=audio.pk, start=start, title=cm.title, link=cm.link, image=cm.image))
        using = using or router.db_for_write(Audio, instance=audio)
        with transaction.atomic(using=using):
            # A no-op UPDATE takes a row lock on PostgreSQL and a write lock on
            # SQLite *before* reading chapters, avoiding a deferred lock upgrade.
            if not Audio.objects.using(using).filter(pk=audio.pk).update(title=models.F("title")):
                raise Audio.DoesNotExist
            from_db = list(ChapterMark.objects.using(using).filter(audio_id=audio.pk))
            if not update_urls:
                by_start = {cm.start: cm for cm in from_db}
                for cm in pending:
                    if cm.start in by_start:
                        cm.link, cm.image = by_start[cm.start].link, by_start[cm.start].image
            to_add, to_update, to_remove = sync_chapter_marks(from_db, pending)
            for cm in to_add + to_update:
                cm.save(using=using)
            for cm in to_remove:
                cm.delete(using=using)


class ChapterMark(models.Model):
    """A navigable chapter marker within an audio file.

    Each mark has a start time, title, and optional link and image URL.
    Unique together on (audio, start). Queries typically order by start time.
    """

    audio = models.ForeignKey(Audio, on_delete=models.CASCADE, related_name="chaptermarks")
    start = models.TimeField(_("Start time of chaptermark"))
    title = models.CharField(max_length=255)
    link = models.URLField(max_length=2000, null=True, blank=True)
    image = models.URLField(max_length=2000, null=True, blank=True)

    objects = ChapterMarkManager()

    class Meta:
        unique_together = (("audio", "start"),)

    def __str__(self) -> str:
        return f"{self.pk} {self.start} {self.title}"

    def has_changed(self, other: "ChapterMark") -> bool:
        return any(
            (getattr(self, field) or "") != (getattr(other, field) or "") for field in ("title", "link", "image")
        )

    @property
    def original_line(self) -> str:
        link = ""
        if self.link is not None:
            link = self.link
        image = ""
        if self.image is not None:
            image = self.image
        return f"{self.start} {self.title} {link} {image}"
