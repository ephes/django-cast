import logging
import os
import subprocess
import tempfile
from pathlib import Path
from subprocess import check_output
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

    @property
    def filename(self) -> str:
        return Path(self.original.name).name

    @property
    def type(self) -> str:
        return "video"

    @staticmethod
    def _get_video_dimensions(video_url: str) -> tuple[int | None, int | None]:
        ffprobe_cmd = f'ffprobe -i "{video_url}"'
        result = subprocess.check_output(ffprobe_cmd, shell=True, stderr=subprocess.STDOUT)
        lines = result.decode("utf8").split("\n")
        return get_video_dimensions(lines)

    def _create_poster(self) -> None:
        """Moved into own method to make it mockable in tests."""
        fp, tmp_path = tempfile.mkstemp(prefix="poster_", suffix=".jpg")
        logger.info(f"original url: {self.original.url}")
        video_url = self.original.url
        if not video_url.startswith("http"):
            video_url = self.original.path
        width, height = self._get_video_dimensions(video_url)
        poster_cmd = (
            'ffmpeg -ss {seconds} -i "{video_path}" -vframes 1 -y -f image2 -s {width}x{height} {poster_path}'
        ).format(
            video_path=video_url,
            seconds=self.poster_seconds,
            poster_path=tmp_path,
            width=width,
            height=height,
        )
        logger.info(poster_cmd)
        check_output(poster_cmd, shell=True)
        name = os.path.basename(tmp_path)
        content = DjangoFile(open(tmp_path, "rb"))
        self.poster.save(name, content, save=False)
        os.unlink(tmp_path)
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
        paths.add(self.original.name)
        if self.poster:
            paths.add(self.poster.name)
        return paths

    def get_mime_type(self) -> str:
        ending = self.original.name.split(".")[-1].lower()
        return {
            "mp4": "video/mp4",
            "mov": "video/quicktime",
            "avi": "video/x-msvideo",
        }.get(ending, "video/mp4")

    def save(self, *args, **kwargs) -> Optional["Video"]:  # type: ignore[override]
        generate_poster = kwargs.pop("poster", True)
        # need to save original first - django file handling is driving me nuts
        result = super().save(*args, **kwargs)
        if generate_poster:
            logger.info("generate video poster")
            # generate poster thumbnail by default, but make it optional
            # for recalc management command
            self.create_poster()
            # save again after adding poster
            result = super().save(*args, **kwargs)
        return result
