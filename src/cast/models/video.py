import json
import logging
import math
import os
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path
from typing import Any, Optional

from django.contrib.auth import get_user_model
from django.core.files import File as DjangoFile
from django.db import models, router
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel
from taggit.managers import TaggableManager
from wagtail.models import CollectionMember, PageManager
from wagtail.search import index
from wagtail.search.queryset import SearchableQuerySetMixin

from ..media_probe import run_media_probe

logger = logging.getLogger(__name__)

MAX_POSTER_SIDE = 8192
MAX_POSTER_PIXELS = 16_777_216


class VideoQuerySet(SearchableQuerySetMixin, models.QuerySet):
    pass


def get_video_dimensions(lines: list[str]) -> tuple[int | None, int | None]:
    """Read the first selected video stream from ffprobe JSON lines."""
    try:
        data = json.loads("\n".join(lines))
    except ValueError:
        return None, None
    streams = data.get("streams") if isinstance(data, dict) else None
    if not isinstance(streams, list):
        return None, None
    stream = next((item for item in streams if isinstance(item, dict) and item.get("codec_type") == "video"), None)
    if stream is None:
        return None, None
    width, height = stream.get("width"), stream.get("height")
    if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
        return None, None
    aspect_text = str(stream.get("sample_aspect_ratio", "1:1"))
    # ffprobe emits rational pairs. Refuse excessive or exponential metadata
    # before Fraction can materialize an arbitrarily large power of ten.
    if len(aspect_text) > 64 or "e" in aspect_text.lower():
        return None, None
    try:
        sample_aspect = Fraction(aspect_text.replace(":", "/"))
        if sample_aspect > 0:
            width = max(1, round(width * sample_aspect))
    except (ValueError, ZeroDivisionError):
        pass
    if width > MAX_POSTER_SIDE or height > MAX_POSTER_SIDE or width * height > MAX_POSTER_PIXELS:
        return None, None
    tags = stream.get("tags")
    rotation = tags.get("rotate", 0) if isinstance(tags, dict) else 0
    side_data = stream.get("side_data_list")
    if isinstance(side_data, list):
        for entry in side_data:
            if isinstance(entry, dict) and "rotation" in entry:
                rotation = entry["rotation"]
                break
    try:
        quarter_turn = math.isclose(float(rotation) % 180, 90, abs_tol=0.001)
    except (TypeError, ValueError, OverflowError):
        quarter_turn = False
    return (height, width) if quarter_turn else (width, height)


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
        ffprobe_cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "V:0",
            "-show_entries",
            "stream=codec_type,width,height,sample_aspect_ratio:stream_tags=rotate:stream_side_data=rotation",
            "-of",
            "json",
            "-i",
            str(video_url),
        ]
        result = run_media_probe(
            ffprobe_cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        ).stdout
        lines = result.decode("utf8").split("\n")
        return get_video_dimensions(lines)

    def _create_poster(self) -> None:
        """Moved into own method to make it mockable in tests."""
        fp, tmp_path = tempfile.mkstemp(prefix="poster_", suffix=".jpg")
        try:
            os.close(fp)
            logger.info("video=%s poster phase=probe", self.pk)
            video_url = self.original.url
            if not video_url.startswith("http"):
                video_url = self.original.path
            width, height = self._get_video_dimensions(video_url)
            if width is None or height is None:
                logger.info("video=%s poster phase=probe result=dimensions-unavailable", self.pk)
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
            logger.info("video=%s poster phase=extract", self.pk)
            run_media_probe(poster_cmd, check=True, timeout=30, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            name = os.path.basename(tmp_path)
            with open(tmp_path, "rb") as tmp_file:
                self.poster.save(name, DjangoFile(tmp_file), save=False)
        finally:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
        logger.info("video=%s poster phase=store result=success", self.pk)

    def create_poster(self, *, raise_errors: bool = False) -> None:
        """Create the poster if it is missing and wanted.

        A failure is only logged by default, so an upload still succeeds without
        a poster. With ``raise_errors`` the exception reaches the caller.
        """
        if self.poster or not self.calc_poster:
            # poster is not null
            logger.info("video=%s poster phase=admission result=skipped", self.pk)
        else:
            try:
                self._create_poster()
            except Exception as exc:
                category = "timeout" if isinstance(exc, subprocess.TimeoutExpired) else "generation-failed"
                logger.info("video=%s poster phase=generation result=%s", self.pk, category)
                if raise_errors:
                    raise

    def publish_missing_poster(self) -> None:
        """Publish only this attempt's poster if its source generation is current.

        Storage names identify generations: consumers must replace originals
        through storage's unique-name policy, rather than overwrite bytes in place.
        """
        expected = {"original": self.original.name, "poster": self.poster.name, "poster_seconds": self.poster_seconds}
        using = self._state.db or router.db_for_write(type(self), instance=self)
        try:
            self.create_poster(raise_errors=True)
            if self.calc_poster and not self.poster:
                raise RuntimeError("no poster was created")
            if self.poster.name == expected["poster"]:
                return
            if (
                not type(self)
                .objects.using(using)
                .filter(pk=self.pk, **expected)
                .update(poster=self.poster.name, modified=timezone.now())
            ):
                raise RuntimeError("video poster generation changed; retry")
        except Exception:
            name = self.poster.name
            if name and name != expected["poster"]:
                # Never retire an editor's object or a published object.
                if not type(self).objects.using(using).filter(poster=name).exists():
                    self.poster.storage.delete(name)
            raise

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

    def save(self, *args: Any, **kwargs: Any) -> Optional["Video"]:  # type: ignore[override]
        generate_poster = kwargs.pop("poster", None)
        if generate_poster:
            from cast.media_derivation import save_video_with_derivations

            return save_video_with_derivations(self, *args, generate_poster=generate_poster, **kwargs)
        return super().save(*args, **kwargs)
