import os
import re
import uuid
import json
import logging
import tempfile
import subprocess

from pathlib import Path
from subprocess import check_output
from collections import defaultdict

from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.files import File as DjangoFile
from django.utils.translation import ugettext_lazy as _

from ckeditor_uploader.fields import RichTextUploadingField

from imagekit.models import ImageSpecField
from imagekit.processors import Thumbnail
from imagekit.processors import Transpose

from model_utils.models import TimeStampedModel

from slugify import slugify


logger = logging.getLogger(__name__)


def image_spec_thumbnail(size):
    processors = [Transpose(), Thumbnail(size, size, crop=False)]
    return ImageSpecField(
        source="original", processors=processors, format="JPEG", options={"quality": 60}
    )


class Image(TimeStampedModel):
    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)

    original = models.ImageField(
        upload_to="cast_images/originals",
        height_field="original_height",
        width_field="original_width",
    )
    original_height = models.PositiveIntegerField(blank=True, null=True)
    original_width = models.PositiveIntegerField(blank=True, null=True)

    img_full = ImageSpecField(
        source="original",
        processors=[Transpose()],
        format="JPEG",
        options={"quality": 60},
    )

    IMAGE_SIZES = {
        "img_full": None,
        "img_xl": 2200,
        "img_lg": 1100,
        "img_md": 768,
        "img_sm": 500,
        "img_xs": 300,
    }

    img_xl = image_spec_thumbnail(IMAGE_SIZES["img_xl"])
    img_lg = image_spec_thumbnail(IMAGE_SIZES["img_lg"])
    img_md = image_spec_thumbnail(IMAGE_SIZES["img_md"])
    img_sm = image_spec_thumbnail(IMAGE_SIZES["img_sm"])
    img_xs = image_spec_thumbnail(IMAGE_SIZES["img_xs"])

    sizes = [(v, k) for k, v in IMAGE_SIZES.items()]

    post_context_key = "image"

    def get_all_paths(self):
        paths = set()
        paths.add(self.original.name)
        for size, attr_name in self.sizes:
            paths.add(getattr(self, attr_name).name)
        return paths

    def __str__(self):
        return self.original.name

    def get_srcset(self):
        sources = []
        for size, attr_name in self.sizes:
            img = getattr(self, attr_name)
            width = self.original_width if size is None else size
            url = img.url
            sources.append(url)
            sources.append("{}w,".format(width))
        return " ".join(sources)

    @property
    def srcset(self):
        return self.get_srcset()

    @property
    def thumbnail_src(self):
        return self.img_xs.url

    @property
    def full_src(self):
        return self.full.url


class ItunesArtWork(TimeStampedModel):
    original = models.ImageField(
        upload_to="cast_images/itunes_artwork",
        height_field="original_height",
        width_field="original_width",
    )
    original_height = models.PositiveIntegerField(blank=True, null=True)
    original_width = models.PositiveIntegerField(blank=True, null=True)


def get_video_dimensions(lines):
    def get_width_height(video_type, line):
        dim_col = line.split(", ")[3]
        if video_type != "h264":
            dim_col = dim_col.split(" ")[0]
        return map(int, dim_col.split("x"))

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
    for line in lines:
        if "rotation of" in line:
            portrait = True
    if portrait:
        width, height = height, width
    return width, height


class Video(TimeStampedModel):
    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
    original = models.FileField(upload_to="cast_videos/")
    poster = models.ImageField(upload_to="cast_videos/poster/", null=True, blank=True)
    poster_seconds = models.FloatField(default=1)

    poster_thumbnail = ImageSpecField(
        source="poster",
        processors=[Thumbnail(300, 300, crop=False)],
        format="JPEG",
        options={"quality": 60},
    )

    post_context_key = "video"
    calc_poster = True

    def _get_video_dimensions(self, video_url):
        ffprobe_cmd = 'ffprobe -i "{}"'.format(video_url)
        result = subprocess.check_output(
            ffprobe_cmd, shell=True, stderr=subprocess.STDOUT
        )
        lines = result.decode("utf8").split("\n")
        return get_video_dimensions(lines)

    def _create_poster(self):
        """Moved into own method to make it mockable in tests."""
        fp, tmp_path = tempfile.mkstemp(prefix="poster_", suffix=".jpg")
        logger.info("original url: {}".format(self.original.url))
        video_url = self.original.url
        if not video_url.startswith("http"):
            video_url = self.original.path
        width, height = self._get_video_dimensions(video_url)
        poster_cmd = (
            'ffmpeg -ss {seconds} -i "{video_path}" -vframes 1'
            " -y -f image2 -s {width}x{height} {poster_path}"
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

    def create_poster(self):
        if self.poster or not self.calc_poster:
            # poster is not null
            logger.info("skip creating poster")
        else:
            try:
                self._create_poster()
            except Exception as e:
                logger.info(e)
                logger.info("create poster failed")

    def get_all_paths(self):
        paths = set()
        paths.add(self.original.name)
        if self.poster:
            paths.add(self.poster.name)
            try:
                if self.poster_thumbnail:
                    paths.add(self.poster_thumbnail.name)
            except FileNotFoundError:
                pass
        return paths

    def save(self, *args, **kwargs):
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


class Gallery(TimeStampedModel):
    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
    images = models.ManyToManyField(Image)
    post_context_key = "gallery"

    @property
    def image_ids(self):
        return set([i.pk for i in self.images.all()])


class Audio(TimeStampedModel):
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
        ffprobe_cmd = 'ffprobe -show_entries format=duration -i "{}"'.format(audio_url)
        result = subprocess.check_output(
            ffprobe_cmd, shell=True, stderr=subprocess.STDOUT
        )
        lines = result.decode("utf8").split("\n")
        duration = None
        for line in lines:
            if "Duration" in line:
                duration = line.split(",")[0].split()[-1]
                break
        return duration

    def create_duration(self):
        for name, field in self.uploaded_audio_files:
            audio_url = field.url
            if not audio_url.startswith("http"):
                audio_url = field.path
            duration = self._get_audio_duration(audio_url)
            # skip duration for small files (tests won't work otherwise :(..)
            if not int(duration.split(":")[2].split(".")[0]) > 0:
                duration = None
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
                    "start": chapter.start.split(".")[0],
                    "title": chapter.title,
                    "href": chapter.link,
                    "image": chapter.image,
                }
            )
        return items

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


class File(TimeStampedModel):
    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
    original = models.FileField(upload_to="cast_files/")

    def get_all_paths(self):
        paths = set()
        paths.add(self.original.name)
        return paths


class Blog(TimeStampedModel):
    user = models.ForeignKey(
        get_user_model(), on_delete=models.CASCADE, related_name="cast_user"
    )
    title = models.CharField(max_length=255)
    description = models.CharField(max_length=500)
    slug = models.SlugField(max_length=50)
    uuid = models.UUIDField(default=uuid.uuid4, editable=False)
    email = models.EmailField(null=True, default=None, blank=True)

    # podcast stuff

    # atm it's only used for podcast image
    itunes_artwork = models.ForeignKey(
        ItunesArtWork, null=True, blank=True, on_delete=models.CASCADE
    )
    itunes_categories = models.CharField(
        _("itunes_categories"),
        max_length=512,
        blank=True,
        default="",
        help_text=_(
            "A json dict of itunes categories pointing to lists "
            "of subcategories. Taken from this list "
            "https://validator.w3.org/feed/docs/error/InvalidItunesCategory.html"
        ),
    )
    EXPLICIT_CHOICES = ((1, _("yes")), (2, _("no")), (3, _("clean")))
    keywords = models.CharField(
        _("keywords"),
        max_length=255,
        blank=True,
        default="",
        help_text=_(
            """A comma-delimitedlist of up to 12 words for iTunes
            searches. Perhaps include misspellings of the title."""
        ),
    )
    explicit = models.PositiveSmallIntegerField(
        _("explicit"),
        default=1,
        choices=EXPLICIT_CHOICES,
        help_text=_("``Clean`` will put the clean iTunes graphic by it."),
    )

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("cast:post_list", kwargs={"slug": self.slug})

    @property
    def last_build_date(self):
        return (
            Post.published.filter(blog=self).order_by("-visible_date")[1].visible_date
        )

    @property
    def itunes_categories_parsed(self):
        try:
            return json.loads(self.itunes_categories)
        except json.decoder.JSONDecodeError:
            return {}

    @property
    def is_podcast(self):
        return self.post_set.exclude(podcast_audio__isnull=True).count() > 0


class PostPublishedManager(models.Manager):
    use_for_related_fields = True

    def get_queryset(self):
        return super().get_queryset().filter(pub_date__lte=timezone.now())

    @property
    def podcast_episodes(self):
        return self.get_queryset().filter(podcast_audio__isnull=False)


class Post(TimeStampedModel):
    uuid = models.UUIDField(default=uuid.uuid4, editable=False)
    author = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
    blog = models.ForeignKey(Blog, on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    pub_date = models.DateTimeField(null=True, blank=True)
    visible_date = models.DateTimeField(default=timezone.now)
    podcast_audio = models.ForeignKey(
        Audio, null=True, blank=True, on_delete=models.CASCADE, related_name="posts"
    )
    keywords = models.CharField(
        _("keywords"),
        max_length=255,
        blank=True,
        default="",
        help_text=_(
            """A comma-demlimitedlist of up to 12 words for iTunes
            searches. Perhaps include misspellings of the title."""
        ),
    )
    explicit = models.PositiveSmallIntegerField(
        _("explicit"),
        choices=Blog.EXPLICIT_CHOICES,
        help_text=_("``Clean`` will put the clean iTunes graphic by it."),
        default=1,
    )
    block = models.BooleanField(
        _("block"),
        default=False,
        help_text=_(
            "Check to block this episode from iTunes because <br />its "
            "content might cause the entire show to be <br />removed from iTunes."
            ""
        ),
    )

    content = RichTextUploadingField()
    slug = models.SlugField(max_length=50)

    images = models.ManyToManyField(Image, blank=True)
    videos = models.ManyToManyField(Video, blank=True)
    galleries = models.ManyToManyField(Gallery, blank=True)
    audios = models.ManyToManyField(Audio, blank=True)

    media_model_lookup = {
        "image": Image,
        "video": Video,
        "gallery": Gallery,
        "audio": Audio,
    }

    objects = models.Manager()
    published = PostPublishedManager()

    @property
    def is_published(self):
        return self.pub_date is not None and self.pub_date < timezone.now()

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        params = {"slug": self.slug, "blog_slug": self.blog.slug}
        return reverse("cast:post_detail", kwargs=params)

    def get_enclosure_url(self, audio_format):
        return getattr(self.podcast_audio, audio_format).url

    def get_enclosure_size(self, audio_format):
        return getattr(self.podcast_audio, audio_format).size

    def get_slug(self):
        return slugify(self.title)

    @property
    def media_lookup_old(self):
        lookup = defaultdict(dict)
        media = list(self.media.all().prefetch_related("content_object"))
        for item in media:
            obj = item.content_object
            lookup[obj.post_context_key][obj.pk] = obj
        return lookup

    @property
    def media_lookup(self):
        return {
            "image": {i.pk: i for i in self.images.all()},
            "video": {v.pk: v for v in self.videos.all()},
            "gallery": {g.pk: g for g in self.galleries.all()},
            "audio": {a.pk: a for a in self.audios.all()},
        }

    @property
    def media_from_content(self):
        regex = re.compile(r"{% (\w+) (\d+) %}")
        groups = regex.findall(self.content)
        media = []
        for name, pk in groups:
            media.append((name, int(pk)))
        return media

    @property
    def media_attr_lookup(self):
        return {
            "image": self.images,
            "video": self.videos,
            "gallery": self.galleries,
            "audio": self.audios,
        }

    def add_missing_media_objects(self):
        media_attr_lookup = self.media_attr_lookup

        media_lookup = self.media_lookup
        model_lookup = self.media_model_lookup
        for model_name, model_pk in self.media_from_content:
            try:
                model = media_lookup[model_name][model_pk]
                logger.info("found: {} {} {}".format(model_name, model_pk, model))
            except KeyError:
                media_object = model_lookup[model_name].objects.get(pk=model_pk)
                media_attr_lookup[model_name].add(media_object)
                logger.info(
                    "added: {} {} {}".format(model_name, model_pk, media_object)
                )

    def remove_obsolete_media_objects(self):
        media_from_db = {k: set(v.keys()) for k, v in self.media_lookup.items()}

        # media from content
        media_content_lookup = defaultdict(set)
        for model_name, model_pk in self.media_from_content:
            media_content_lookup[model_name].add(model_pk)

        # remove all PKs which are in db but not in content
        media_attr_lookup = self.media_attr_lookup
        for media_type, media_pks in media_from_db.items():
            for media_pk in media_pks:
                if media_pk not in media_content_lookup.get(media_type, set()):
                    media_attr_lookup[media_type].remove(media_pk)

    @property
    def has_audio(self):
        return self.audios.count() > 0 or self.podcast_audio is not None

    def save(self, *args, **kwargs):
        save_return = super().save(*args, **kwargs)
        self.add_missing_media_objects()
        self.remove_obsolete_media_objects()
        return save_return


class ChapterMark(models.Model):
    audio = models.ForeignKey(
        Audio, on_delete=models.CASCADE, related_name="chaptermarks"
    )
    start = models.CharField(max_length=12)
    title = models.CharField(max_length=255)
    link = models.URLField(max_length=2000, null=True, blank=True)
    image = models.URLField(max_length=2000, null=True, blank=True)

    class Meta:
        unique_together = (("audio", "start"),)

    def __str__(self):
        return f"{self.pk} {self.start} {self.title}"

    @property
    def original_line(self):
        link = ""
        if self.link is not None:
            link = self.link
        image = ""
        if self.image is not None:
            image = self.image
        return f"{self.start} {self.title} {link} {image}"
