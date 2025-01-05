import json
import logging
import re
import subprocess
from collections.abc import Iterable
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Protocol, runtime_checkable

from django.contrib.auth import get_user_model
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel
from taggit.managers import TaggableManager
from wagtail.models import CollectionMember, PageManager
from wagtail.search import index
from wagtail.search.queryset import SearchableQuerySetMixin

if TYPE_CHECKING:
    from .pages import Episode

logger = logging.getLogger(__name__)


class AudioQuerySet(SearchableQuerySetMixin, models.QuerySet):
    pass


@runtime_checkable
class FileField(Protocol):
    """Just to make mypy happy about field.url and field.path"""

    url: str
    path: str


class Audio(CollectionMember, index.Indexed, TimeStampedModel):  # type: ignore[django-manager-missing]
    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
    duration = models.DurationField(null=True, blank=True)
    title = models.CharField(max_length=255, null=True, blank=True)
    subtitle = models.CharField(max_length=512, null=True, blank=True)

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

    admin_form_fields: tuple[str, ...] = ("title", "subtitle", "m4a", "mp3", "oga", "opus", "tags")

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

    @property
    def uploaded_audio_files(self) -> Iterable[tuple[str, models.FileField]]:
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
    def _get_audio_duration(audio_url) -> timedelta:
        # Taken from: http://trac.ffmpeg.org/wiki/FFprobeTips
        cmd = f"""
        ffprobe  \
            -v 0  \
            -print_format json  \
            -show_entries format=duration  \
            -of default=noprint_wrappers=1:nokey=1  \
            '{audio_url}'
        """
        result = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT).decode().strip()
        m = re.match(r"^(?P<seconds>\d+)\.(?P<microseconds>\d+)$", result)
        if m is None:
            raise ValueError(f"Could not parse duration: {result}")
        return timedelta(seconds=int(m["seconds"]), microseconds=int(m["microseconds"]))

    def create_duration(self) -> None:
        for name, field in self.uploaded_audio_files:
            try:
                # For mypy this has to be a direct isinstance check
                # In production it raises a NotImplementedError, very weird,
                # very ugly, dunno how to fix it
                if isinstance(field, FileField):
                    audio_url = field.url
                    if not audio_url.startswith("http"):
                        audio_url = field.path
                    self.duration = self._get_audio_duration(audio_url)
                    break
            except NotImplementedError:  # pragma: no cover
                pass

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

    @property
    def chapters(self) -> list[dict[str, str | None]]:
        items = []
        # chapter marks have to be ordered by start for
        # podlove web player - dunno why, 2019-04-19 jochen
        for chapter in self.chaptermarks.order_by("start"):
            items.append(
                {
                    "start": str(chapter.start).split(".")[0],
                    "title": chapter.title,
                    "href": chapter.link,  # could be None
                    "image": chapter.image,  # could be None
                }
            )
        return items

    @property
    def chapters_as_text(self) -> str:
        chaptermarks = []
        for mark in self.chaptermarks.order_by("start"):
            chaptermarks.append(mark.original_line)
        return "\n".join(chaptermarks)

    @staticmethod
    def clean_ffprobe_chaptermarks(ffprobe_data: dict) -> list[dict[str, str]]:
        cleaned = []
        for item in ffprobe_data["chapters"]:
            start = item["start_time"]
            title = item["tags"]["title"]
            if title == "":
                continue
            cleaned.append({"start": start, "title": title})
        return cleaned

    def get_chaptermark_data_from_file(self, audio_format: str) -> list[dict[str, str]]:
        file_field = getattr(self, audio_format)
        try:
            url = file_field.url
        except ValueError:
            return []
        if not url.startswith("http"):
            # use path from local filesystem
            url = file_field.path
        command = [
            "ffprobe",
            "-i",
            str(url),
            "-print_format",
            "json",
            "-show_chapters",
            "-loglevel",
            "error",
        ]
        ffprobe_data = json.loads(subprocess.run(command, check=True, stdout=subprocess.PIPE).stdout)
        return self.clean_ffprobe_chaptermarks(ffprobe_data)

    def set_episode_id(self, episode_id: int) -> None:
        """Set the episode id for this audio file to be able to return audio.episode_url in api."""
        self._episode_id = episode_id

    def get_episode(self, episode_id=None) -> Optional["Episode"]:
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
        dur = str(self.duration)
        return dur.split(".")[0]

    def size_to_metadata(self) -> None:
        self.data["size"] = self.data.get("size", {})
        for audio_format, field in self.uploaded_audio_files:
            try:
                assert hasattr(field, "size"), f"field {field} has no size attribute"
                self.data["size"][audio_format] = field.size
            except FileNotFoundError:
                # file does not exist -> do not cache
                pass

    def get_file_size(self, audio_format: str) -> int:
        """Return the file size of the given audio format."""
        cached_size = self.data.get("size", {}).get(audio_format)
        if cached_size is not None:
            return cached_size
        file_field = getattr(self, audio_format)
        try:
            assert hasattr(file_field, "size"), f"field {file_field} has no size attribute"
            return file_field.size
        except ValueError:
            # file_field is null
            return 0

    def save(self, *args, **kwargs) -> None:
        generate_duration = kwargs.pop("duration", True)
        cache_file_sizes = kwargs.pop("cache_file_sizes", True)
        # FIXME why is this necessary? Cannot move super save to end of method...
        super().save(*args, **kwargs)
        if generate_duration and self.duration is None:
            logger.info("save audio duration")
            self.create_duration()
            super().save(*args, **kwargs)
        if cache_file_sizes:
            self.size_to_metadata()
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
                cm.pk = cm_from_db.pk  # to be able to just call cm.save() later on
                to_update.append(cm)
    to_remove = [cm for cm in from_database if cm.start not in start_from_cms]
    return to_add, to_update, to_remove


class ChapterMarkManager(models.Manager):
    @staticmethod
    def sync_chaptermarks(audio: Audio, from_cms: list["ChapterMark"]) -> None:
        from_db: list["ChapterMark"] = list(audio.chaptermarks.all())
        to_add, to_update, to_remove = sync_chapter_marks(from_db, from_cms)
        for cm in to_add + to_update:
            cm.save()
        for cm in to_remove:
            cm.delete()


class ChapterMark(models.Model):
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
        return self.title != other.title

    @property
    def original_line(self) -> str:
        link = ""
        if self.link is not None:
            link = self.link
        image = ""
        if self.image is not None:
            image = self.image
        return f"{self.start} {self.title} {link} {image}"
