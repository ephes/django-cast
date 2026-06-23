import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from django.contrib.auth import get_user_model
from django.core.files import File as DjangoFile
from django.db import models
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel
from taggit.managers import TaggableManager
from wagtail.models import CollectionMember, PageManager
from wagtail.search import index
from wagtail.search.queryset import SearchableQuerySetMixin

from ..media_validation import validate_video_upload

logger = logging.getLogger(__name__)


class VideoQuerySet(SearchableQuerySetMixin, models.QuerySet):
    pass


def get_video_dimensions(lines: list[str]) -> tuple[int | None, int | None]:
    """Has its own function to be easier to test."""

    def get_width_height(my_video_type, my_line) -> tuple[int, int]:
        dim_col = my_line.split(", ")[3]
        if my_video_type != "h264":
            dim_col = dim_col.split(" ")[0]
        dim_x, dim_y = tuple(map(int, dim_col.split("x")))
        return dim_x, dim_y

    width, height = None, None
    video_types = ("SAR", "hevc", "h264")
    for line in lines:
        for video_type in video_types:
            if video_type in line:
                width, height = get_width_height(video_type, line)
                break
        else:
            # necessary to break out of nested loop
            continue
        break
    portrait = False
    portrait_triggers = ["rotation of", "DAR 9:16"]
    for line in lines:
        for portrait_trigger in portrait_triggers:
            if portrait_trigger in line:
                portrait = True
    if portrait:
        width, height = height, width
    return width, height


class Video(CollectionMember, index.Indexed, TimeStampedModel):
    """Represents an uploaded video file with automatic poster frame extraction.

    Uses FFmpeg/FFprobe for poster generation and dimension detection.
    Videos belong to Wagtail collections and are user-owned.
    """

    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
    title = models.CharField(default="", max_length=255)
    original = models.FileField(upload_to="cast_videos/")
    poster = models.ImageField(upload_to="cast_videos/poster/", null=True, blank=True)
    poster_seconds = models.FloatField(default=1)

    post_context_key = "video"
    calc_poster = True

    admin_form_fields = ("title", "original", "poster", "tags")
    objects: PageManager["Video"] = VideoQuerySet.as_manager()
    tags = TaggableManager(help_text=None, blank=True, verbose_name=_("tags"))

    search_fields = CollectionMember.search_fields + [
        index.SearchField("title", boost=10),
        index.RelatedFields(
            "tags",
            [
                index.SearchField("name", boost=10),
            ],
        ),
        index.FilterField("user"),
    ]

    class Meta:
        permissions = (("choose_video", "Can choose video"),)

    @property
    def filename(self) -> str:
        return Path(self.original.name or "").name

    @property
    def type(self) -> str:
        return "video"

    @staticmethod
    def _get_video_dimensions(video_url: str) -> tuple[int | None, int | None]:
        ffprobe_cmd = ["ffprobe", "-i", str(video_url)]
        result = subprocess.run(
            ffprobe_cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
        ).stdout
        lines = result.decode("utf8").split("\n")
        return get_video_dimensions(lines)

    def _create_poster(self) -> None:
        """Moved into own method to make it mockable in tests."""
        fp, tmp_path = tempfile.mkstemp(prefix="poster_", suffix=".jpg")
        try:
            os.close(fp)
            logger.info(f"original url: {self.original.url}")
            video_url = self.original.url
            if not video_url.startswith("http"):
                video_url = self.original.path
            width, height = self._get_video_dimensions(video_url)
            if width is None or height is None:
                logger.info("skip creating poster: video dimensions unavailable")
                return
            poster_cmd = [
                "ffmpeg",
                "-ss",
                str(self.poster_seconds),
                "-i",
                str(video_url),
                "-vframes",
                "1",
                "-y",
                "-f",
                "image2",
                "-s",
                f"{width}x{height}",
                tmp_path,
            ]
            logger.info(poster_cmd)
            subprocess.run(poster_cmd, check=True, timeout=30)
            name = os.path.basename(tmp_path)
            with open(tmp_path, "rb") as tmp_file:
                self.poster.save(name, DjangoFile(tmp_file), save=False)
        finally:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
        logger.info(self.pk)
        logger.info(self.poster)

    def create_poster(self) -> None:
        if self.poster or not self.calc_poster:
            # poster is not null
            logger.info("skip creating poster")
        else:
            try:
                self._create_poster()
            except Exception as e:
                logger.info(e)
                logger.info("create poster failed")

    def get_all_paths(self) -> set[str]:
        paths = set()
        if self.original.name:
            paths.add(self.original.name)
        if self.poster.name:
            paths.add(self.poster.name)
        return paths

    def get_mime_type(self) -> str:
        ending = (self.original.name or "").split(".")[-1].lower()
        return {
            "mp4": "video/mp4",
            "mov": "video/quicktime",
            "avi": "video/x-msvideo",
        }.get(ending, "video/mp4")

    def save(self, *args, **kwargs) -> Optional["Video"]:  # type: ignore[override]
        generate_poster = kwargs.pop("poster", True)
        if generate_poster and not getattr(self.original, "_committed", True):
            validate_video_upload(self.original.file)
        # need to save original first - django file handling is driving me nuts
        result = super().save(*args, **kwargs)
        if generate_poster:
            logger.info("generate video poster")
            # generate poster thumbnail by default, but make it optional
            # for recalc management command
            poster_name_before = self.poster.name or ""
            self.create_poster()
            poster_name_after = self.poster.name or ""
            if poster_name_after and poster_name_after != poster_name_before:
                save_kwargs = {"update_fields": ["poster"]}
                using = kwargs.get("using")
                if using is not None:
                    save_kwargs["using"] = using
                result = super().save(**save_kwargs)
        return result
