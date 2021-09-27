import json
import logging
import re
import subprocess

from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from wagtail.core.models import CollectionMember
from wagtail.search import index
from wagtail.search.queryset import SearchableQuerySetMixin

from model_utils.models import TimeStampedModel
from taggit.managers import TaggableManager


logger = logging.getLogger(__name__)


class AudioQuerySet(SearchableQuerySetMixin, models.QuerySet):
    pass


class Audio(CollectionMember, index.Indexed, TimeStampedModel):
    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
    duration = models.DurationField(null=True, blank=True)
    title = models.CharField(max_length=255, null=True, blank=True)
    subtitle = models.CharField(max_length=512, null=True, blank=True)

    m4a = models.FileField(upload_to="cast_audio/", null=True, blank=True)
    mp3 = models.FileField(upload_to="cast_audio/", null=True, blank=True)
    oga = models.FileField(upload_to="cast_audio/", null=True, blank=True)
    opus = models.FileField(upload_to="cast_audio/", null=True, blank=True)

    mime_lookup = {
        "mp3": "audio/mpeg",
        "m4a": "audio/mp4",
        "oga": "audio/ogg",
        "opus": "audio/opus",
    }
    audio_formats = list(mime_lookup.keys())
    title_lookup = {key: f"Audio {key.upper()}" for key in audio_formats}

    admin_form_fields = ("title", "subtitle", "m4a", "mp3", "oga", "opus", "tags")
    tags = TaggableManager(help_text=None, blank=True, verbose_name=_("tags"))

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

    objects = AudioQuerySet.as_manager()

    @property
    def uploaded_audio_files(self):
        for name in self.audio_formats:
            field = getattr(self, name)
            if field.name is not None and len(field.name) > 0:
                yield name, field

    @property
    def file_formats(self):
        return " ".join([n for n, f in self.uploaded_audio_files])

    def get_audio_file_names(self):
        audio_file_names = set()
        for audio_format, field in self.uploaded_audio_files:
            audio_file_names.add(Path(field.name).stem)
        return audio_file_names

    @property
    def name(self):
        if self.title is not None:
            return self.title
        return ",".join([_ for _ in self.get_audio_file_names()])

    def __str__(self):
        return f"{self.pk} - {self.name}"

    def get_all_paths(self):
        paths = set()
        for name, field in self.uploaded_audio_files:
            paths.add(field.name)
        return paths

    def _get_audio_duration(self, audio_url):
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
        return timedelta(seconds=int(m["seconds"]), microseconds=int(m["microseconds"]))

    def create_duration(self):
        for name, field in self.uploaded_audio_files:
            audio_url = field.url
            if not audio_url.startswith("http"):
                audio_url = field.path
            duration = self._get_audio_duration(audio_url)
            if duration is not None:
                self.duration = duration
                break

    @property
    def audio(self):
        items = []
        for name, field in self.uploaded_audio_files:
            items.append(
                {
                    "url": field.url,
                    "mimeType": self.mime_lookup[name],
                    "size": field.size,
                    "title": self.title_lookup[name],
                }
            )
        return items

    @property
    def chapters(self):
        items = []
        # chapter marks have to be ordered by start for
        # podlove web player - dunno why, 2019-04-19 jochen
        for chapter in self.chaptermarks.order_by("start"):
            items.append(
                {
                    "start": str(chapter.start).split(".")[0],
                    "title": chapter.title,
                    "href": chapter.link,
                    "image": chapter.image,
                }
            )
        return items

    @property
    def chapters_as_text(self):
        chaptermarks = []
        for mark in self.chaptermarks.order_by("start"):
            chaptermarks.append(mark.original_line)
        return "\n".join(chaptermarks)

    @staticmethod
    def clean_ffprobe_chaptermarks(ffprobe_data):
        cleaned = []
        for item in ffprobe_data["chapters"]:
            start = item["start_time"]
            title = item["tags"]["title"]
            if title == "":
                continue
            cleaned.append({"start": start, "title": title})
        return cleaned

    def get_chaptermark_data_from_file(self, audio_format):
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

    @property
    def podlove_url(self):
        return reverse("cast:api:audio_podlove_detail", kwargs={"pk": self.pk})

    @property
    def duration_str(self):
        dur = str(self.duration)
        return dur.split(".")[0]

    def save(self, *args, **kwargs):
        generate_duration = kwargs.pop("duration", True)
        result = super().save(*args, **kwargs)
        if generate_duration and self.duration is None:
            logger.info("save audio duration")
            self.create_duration()
            result = super().save(*args, **kwargs)
        return result


def sync_chapter_marks(from_database, from_cms):
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
    def sync_chaptermarks(audio, from_cms):
        from_db = list(audio.chaptermarks.all())
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

    def __str__(self):
        return f"{self.pk} {self.start} {self.title}"

    def has_changed(self, other):
        return self.title != other.title

    @property
    def original_line(self):
        link = ""
        if self.link is not None:
            link = self.link
        image = ""
        if self.image is not None:
            image = self.image
        return f"{self.start} {self.title} {link} {image}"
