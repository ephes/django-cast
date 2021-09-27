import uuid

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from wagtail.admin.edit_handlers import FieldPanel, StreamFieldPanel
from wagtail.core import blocks
from wagtail.core.fields import StreamField
from wagtail.core.models import Page, PageManager
from wagtail.embeds.blocks import EmbedBlock
from wagtail.images.blocks import ImageChooserBlock
from wagtail.images.models import Image
from wagtail.search import index

from model_utils.models import TimeStampedModel
from slugify import slugify

from cast import appsettings
from cast.blocks import AudioChooserBlock, GalleryBlock, VideoChooserBlock
from cast.models import get_or_create_gallery
from cast.models.blog import Blog


class ContentBlock(blocks.StreamBlock):
    heading = blocks.CharBlock(classname="full title")
    paragraph = blocks.RichTextBlock()
    image = ImageChooserBlock(template="cast/image/image.html")
    gallery = GalleryBlock(ImageChooserBlock())
    embed = EmbedBlock()
    video = VideoChooserBlock(template="cast/video/video.html", icon="media")
    audio = AudioChooserBlock(template="cast/audio/audio.html", icon="media")

    class Meta:
        icon = "form"


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
    podcast_audio = models.ForeignKey(
        "cast.Audio", null=True, blank=True, on_delete=models.SET_NULL, related_name="posts"
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
    comments_enabled = models.BooleanField(
        _("comments_enabled"),
        default=True,
        help_text=_("Whether comments are enabled for this post." ""),
    )

    images = models.ManyToManyField(Image, blank=True)
    videos = models.ManyToManyField("cast.Video", blank=True)
    galleries = models.ManyToManyField("cast.Gallery", blank=True)
    audios = models.ManyToManyField("cast.Audio", blank=True)

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
    def media_model_lookup(self):
        from .audio import Audio
        from .gallery import Gallery
        from .video import Video

        return {
            "image": Image,
            "video": Video,
            "gallery": Gallery,
            "audio": Audio,
        }

    @property
    def blog(self):
        """
        The get_parent() method returns wagtail parent page, which is not
        necessarily a Blog model, but maybe the root page. If it's a Blog
        it has a .blog attribute containing the model which has all the
        attributes like blog.comments_enabled etc..
        """
        return self.get_parent().blog

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
        try:
            return {
                "image": {i.pk: i for i in self.images.all()},
                "video": {v.pk: v for v in self.videos.all()},
                "gallery": {g.pk: g for g in self.galleries.all()},
                "audio": {a.pk: a for a in self.audios.all()},
            }
        except ValueError:
            # post ist not yet saved
            pass

    @property
    def media_attr_lookup(self):
        return {
            "image": self.images,
            "video": self.videos,
            "gallery": self.galleries,
            "audio": self.audios,
        }

    @property
    def audio_in_body(self):
        audio_blocks = []
        for block in self.body:
            for content_block in block.value:
                if content_block.block_type == "audio":
                    audio_blocks.append(content_block)
        return len(audio_blocks) > 0

    @property
    def has_audio(self):
        return self.audio_in_body or self.audios.count() > 0 or self.podcast_audio is not None

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
