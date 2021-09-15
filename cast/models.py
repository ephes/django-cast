import json
import logging
import os
import re
import subprocess
import tempfile
import uuid

from datetime import timedelta
from pathlib import Path
from subprocess import check_output

from django.contrib.auth import get_user_model
from django.core.files import File as DjangoFile
from django.db import models
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from wagtail.admin.edit_handlers import FieldPanel, StreamFieldPanel
from wagtail.core import blocks
from wagtail.core.fields import RichTextField, StreamField
from wagtail.core.models import CollectionMember, Page, PageManager
from wagtail.embeds.blocks import EmbedBlock
from wagtail.images.blocks import ImageChooserBlock
from wagtail.images.models import Image as WagtailImage
from wagtail.search import index
from wagtail.search.queryset import SearchableQuerySetMixin

from imagekit.models import ImageSpecField
from imagekit.processors import Thumbnail, Transpose
from model_utils.models import TimeStampedModel
from slugify import slugify
from taggit.managers import TaggableManager

from . import appsettings
from .blocks import AudioChooserBlock, GalleryBlock, VideoChooserBlock


logger = logging.getLogger(__name__)


def image_spec_thumbnail(size):  #
    processors = [Transpose(), Thumbnail(size, size, crop=False)]
    return ImageSpecField(source="original", processors=processors, format="JPEG", options={"quality": 60})


class Image(TimeStampedModel):
    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE, related_name="cast_images")

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
        return self.img_full.url


class ItunesArtWork(TimeStampedModel):
    original = models.ImageField(
        upload_to="cast_images/itunes_artwork",
        height_field="original_height",
        width_field="original_width",
    )
    original_height = models.PositiveIntegerField(blank=True, null=True)
    original_width = models.PositiveIntegerField(blank=True, null=True)


def get_video_dimensions(lines):
    """Has it's own function to be easier to test."""

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
    portrait_triggers = ["rotation of", "DAR 9:16"]
    for line in lines:
        for portrait_trigger in portrait_triggers:
            if portrait_trigger in line:
                portrait = True
    if portrait:
        width, height = height, width
    return width, height


class VideoQuerySet(SearchableQuerySetMixin, models.QuerySet):
    pass


class Video(CollectionMember, index.Indexed, TimeStampedModel):
    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
    title = models.CharField(default="", max_length=255)
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

    admin_form_fields = ("title", "original", "poster", "tags")
    tags = TaggableManager(help_text=None, blank=True, verbose_name=_("tags"))

    objects = VideoQuerySet.as_manager()

    search_fields = CollectionMember.search_fields + [
        index.SearchField("title", partial_match=True, boost=10),
        index.RelatedFields(
            "tags",
            [
                index.SearchField("name", partial_match=True, boost=10),
            ],
        ),
        index.FilterField("user"),
    ]

    @property
    def filename(self):
        return Path(self.original.name).name

    @property
    def type(self):
        return "video"

    def _get_video_dimensions(self, video_url):
        ffprobe_cmd = 'ffprobe -i "{}"'.format(video_url)
        result = subprocess.check_output(ffprobe_cmd, shell=True, stderr=subprocess.STDOUT)
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
            'ffmpeg -ss {seconds} -i "{video_path}" -vframes 1' " -y -f image2 -s {width}x{height} {poster_path}"
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
            except (FileNotFoundError, OSError):
                pass
        return paths

    def get_mime_type(self):
        ending = self.original.name.split(".")[-1].lower()
        return {
            "mp4": "video/mp4",
            "mov": "video/quicktime",
            "avi": "video/x-msvideo",
        }.get(ending, "video/mp4")

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
    images = models.ManyToManyField(WagtailImage)
    post_context_key = "gallery"

    @property
    def image_ids(self):
        return set([i.pk for i in self.images.all()])


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


class HomePage(Page):
    body = StreamField(
        [
            ("heading", blocks.CharBlock(classname="full title")),
            ("paragraph", blocks.RichTextBlock()),
            ("image", ImageChooserBlock(template="cast/wagtail_image.html")),
            ("gallery", GalleryBlock(ImageChooserBlock())),
        ]
    )
    alias_for_page = models.ForeignKey(
        "wagtailcore.Page",
        related_name="aliases_homepage",
        null=True,
        blank=True,
        default=None,
        on_delete=models.SET_NULL,
        verbose_name="Redirect to another page",
        help_text="Make this page an alias for another page, redirecting to it with a non permanent redirect.",
    )

    content_panels = Page.content_panels + [
        FieldPanel("alias_for_page"),
        StreamFieldPanel("body"),
    ]

    def serve(self, request):
        if self.alias_for_page is not None:
            return redirect(self.alias_for_page.url, permanent=False)
        return super().serve(request)


class Blog(TimeStampedModel, Page):
    author = models.CharField(max_length=255, default=None, null=True, blank=True)
    uuid = models.UUIDField(default=uuid.uuid4, editable=False)
    email = models.EmailField(null=True, default=None, blank=True)
    comments_enabled = models.BooleanField(
        _("comments_enabled"),
        default=True,
        help_text=_("Whether comments are enabled for this blog." ""),
    )

    # podcast stuff

    # atm it's only used for podcast image
    itunes_artwork = models.ForeignKey(ItunesArtWork, null=True, blank=True, on_delete=models.SET_NULL)
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

    # wagtail
    description = RichTextField(blank=True)
    template = "cast/blog_list_of_posts.html"
    content_panels = Page.content_panels + [
        FieldPanel("description", classname="full"),
        FieldPanel("email"),
    ]

    subpage_types = ["cast.Post"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("cast:post_list", kwargs={"slug": self.slug})

    @property
    def last_build_date(self):
        return Post.objects.live().descendant_of(self.blog).order_by("-visible_date")[0].visible_date

    @property
    def itunes_categories_parsed(self):
        try:
            return json.loads(self.itunes_categories)
        except json.decoder.JSONDecodeError:
            return {}

    @property
    def is_podcast(self):
        return Post.objects.live().descendant_of(self).exclude(podcast_audio__isnull=True).count() > 0

    @property
    def author_name(self):
        if self.author is not None:
            return self.author
        else:
            return self.owner.get_full_name()

    @property
    def unfiltered_published_posts(self):
        return Post.objects.live().descendant_of(self).order_by("-visible_date")

    @property
    def request(self):
        if hasattr(self, "_request"):
            return self._request

        class StubRequest:
            GET = {}

        return StubRequest()

    @request.setter
    def request(self, value):
        self._request = value

    @property
    def filterset(self):
        from .filters import PostFilter

        return PostFilter(data=self.request.GET, queryset=self.unfiltered_published_posts, fetch_facet_counts=True)

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        self.request = request
        context["filter"] = self.filterset
        return context

    @property
    def published_posts(self):
        return self.filterset.qs


class ContentBlock(blocks.StreamBlock):
    heading = blocks.CharBlock(classname="full title")
    paragraph = blocks.RichTextBlock()
    image = ImageChooserBlock(template="cast/wagtail_image.html")
    gallery = GalleryBlock(ImageChooserBlock())
    embed = EmbedBlock()
    video = VideoChooserBlock(template="cast/wagtail_video.html", icon="media")
    audio = AudioChooserBlock(template="cast/wagtail_audio.html", icon="media")

    class Meta:
        icon = "form"


def get_or_create_gallery(image_ids):
    candidate_images = WagtailImage.objects.filter(id__in=image_ids)  # FIXME filter permissions
    if candidate_images.count() == 0:
        return None
    filtered_image_ids = [ci.id for ci in candidate_images]
    gallery_to_image_ids = {}
    # FIXME filter permissions - fetch only images / galleries that
    # this user has permission to view
    candidate_galleries = Gallery.objects.filter(images__in=filtered_image_ids).prefetch_related("images")
    for gallery in candidate_galleries:
        gallery_to_image_ids[frozenset(i.id for i in gallery.images.all())] = gallery
    gallery = gallery_to_image_ids.get(frozenset(filtered_image_ids))
    if gallery is None:
        gallery = Gallery.objects.create()
        gallery.images.add(*filtered_image_ids)
    return gallery


def sync_media_ids(from_database, from_body):
    to_add, to_remove = {}, {}
    all_media_types = set(from_database.keys()).union(from_body.keys())
    for media_type in all_media_types:
        in_database_ids = from_database.get(media_type, set())
        in_body_ids = from_body.get(media_type, set())
        ids_to_add = in_body_ids - in_database_ids
        if len(ids_to_add) > 0:
            to_add[media_type] = ids_to_add
        ids_to_remove = in_database_ids - in_body_ids
        if len(ids_to_remove) > 0:
            to_remove[media_type] = ids_to_remove
    return to_add, to_remove


class PostPublishedManager(PageManager):
    use_for_related_fields = True

    def get_queryset(self):
        return super().get_queryset().filter(pub_date__lte=timezone.now())

    @property
    def podcast_episodes(self):
        return self.get_queryset().filter(podcast_audio__isnull=False)


class Post(TimeStampedModel, Page):
    uuid = models.UUIDField(default=uuid.uuid4, editable=False)
    pub_date = models.DateTimeField(null=True, blank=True)
    visible_date = models.DateTimeField(default=timezone.now)
    podcast_audio = models.ForeignKey(Audio, null=True, blank=True, on_delete=models.SET_NULL, related_name="posts")
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
    comments_enabled = models.BooleanField(
        _("comments_enabled"),
        default=True,
        help_text=_("Whether comments are enabled for this post." ""),
    )

    images = models.ManyToManyField(WagtailImage, blank=True)
    videos = models.ManyToManyField(Video, blank=True)
    galleries = models.ManyToManyField(Gallery, blank=True)
    audios = models.ManyToManyField(Audio, blank=True)

    media_model_lookup = {
        "image": WagtailImage,
        "video": Video,
        "gallery": Gallery,
        "audio": Audio,
    }

    # wagtail
    body = StreamField(
        [
            ("overview", ContentBlock()),
            ("detail", ContentBlock()),
        ]
    )

    search_fields = Page.search_fields + [
        index.SearchField("body"),
    ]

    content_panels = Page.content_panels + [
        FieldPanel("visible_date"),
        StreamFieldPanel("body"),
    ]
    template = "cast/post.html"
    parent_page_types = ["cast.Blog"]

    # managers
    objects = PageManager()
    published = PostPublishedManager()

    @property
    def blog(self):
        """
        The get_parent() method returns wagtail parent page, which is not
        necessarily a Blog model, but maybe the root page. If it's a Blog
        it has a .blog attribute containing the model which has all the
        attributes like blog.comments_enabled etc..
        """
        return self.get_parent().blog

    def get_absolute_url(self):
        return self.get_full_url()

    @property
    def is_published(self):
        return self.pub_date is not None and self.pub_date < timezone.now()

    def __str__(self):
        return self.title

    def get_enclosure_url(self, audio_format):
        return getattr(self.podcast_audio, audio_format).url

    def get_enclosure_size(self, audio_format):
        return getattr(self.podcast_audio, audio_format).size

    def get_slug(self):
        return slugify(self.title)

    @property
    def media_lookup(self):
        return {
            "image": {i.pk: i for i in self.images.all()},
            "video": {v.pk: v for v in self.videos.all()},
            "gallery": {g.pk: g for g in self.galleries.all()},
            "audio": {a.pk: a for a in self.audios.all()},
        }

    @property
    def media_attr_lookup(self):
        return {
            "image": self.images,
            "video": self.videos,
            "gallery": self.galleries,
            "audio": self.audios,
        }

    @property
    def has_audio(self):
        return self.audios.count() > 0 or self.podcast_audio is not None

    @property
    def comments_are_enabled(self):
        return appsettings.CAST_COMMENTS_ENABLED and self.blog.comments_enabled and self.comments_enabled

    def get_context(self, *args, **kwargs):
        context = super().get_context(*args, **kwargs)
        context["render_detail"] = kwargs.get("render_detail", False)
        return context

    @property
    def media_ids_from_db(self):
        return {k: set(v) for k, v in self.media_lookup.items()}

    @property
    def media_ids_from_body(self):
        from_body = {}
        for content_block in self.body:
            for block in content_block.value:
                if block.block_type == "gallery":
                    image_ids = [i.id for i in block.value]
                    print("block value: ", block.value)
                    media_model = get_or_create_gallery(image_ids)
                else:
                    media_model = block.value
                if block.block_type in self.media_model_lookup:
                    from_body.setdefault(block.block_type, set()).add(media_model.id)
        return from_body

    def sync_media_ids(self):
        media_attr_lookup = self.media_attr_lookup
        to_add, to_remove = sync_media_ids(self.media_ids_from_db, self.media_ids_from_body)

        # add new ids
        for media_type, ids in to_add.items():
            for media_id in ids:
                media_attr_lookup[media_type].add(media_id)

        # remove obsolete ids
        for media_type, ids in to_remove.items():
            for media_id in ids:
                media_attr_lookup[media_type].remove(media_id)

    def save(self, *args, **kwargs):
        save_return = super().save(*args, **kwargs)
        self.sync_media_ids()
        return save_return


class ChapterMark(models.Model):
    audio = models.ForeignKey(Audio, on_delete=models.CASCADE, related_name="chaptermarks")
    start = models.TimeField(_("Start time of chaptermark"))
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


class Request(models.Model):
    """
    Hold requests from access.log files.
    """

    ip = models.GenericIPAddressField()
    timestamp = models.DateTimeField()
    status = models.PositiveSmallIntegerField()
    size = models.PositiveIntegerField()
    referer = models.CharField(max_length=2048, blank=True, null=True)
    user_agent = models.CharField(max_length=1024, blank=True, null=True)

    REQUEST_METHOD_CHOICES = [
        (1, "GET"),
        (2, "HEAD"),
        (3, "POST"),
        (4, "PUT"),
        (5, "PATCH"),
        (6, "DELETE"),
        (7, "OPTIONS"),
        (8, "CONNECT"),
        (8, "TRACE"),
    ]
    method = models.PositiveSmallIntegerField(choices=REQUEST_METHOD_CHOICES)

    path = models.CharField(max_length=1024)

    HTTP_PROTOCOL_CHOICES = [(1, "HTTP/1.0"), (2, "HTTP/1.1"), (3, "HTTP/2.0")]
    protocol = models.PositiveSmallIntegerField(choices=HTTP_PROTOCOL_CHOICES)

    def __str__(self):
        return f"{self.pk} {self.ip} {self.path}"
