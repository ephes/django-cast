import logging
import uuid

from django.db import models
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from django.utils.safestring import SafeText
from django.utils.translation import gettext_lazy as _
from slugify import slugify
from wagtail.admin.edit_handlers import FieldPanel
from wagtail.core import blocks
from wagtail.core.fields import StreamField
from wagtail.core.models import Page, PageManager
from wagtail.embeds.blocks import EmbedBlock
from wagtail.images.blocks import ImageChooserBlock
from wagtail.images.models import Image
from wagtail.search import index

from cast import appsettings
from cast.blocks import AudioChooserBlock, CodeBlock, GalleryBlock, VideoChooserBlock
from cast.models import get_or_create_gallery

logger = logging.getLogger(__name__)


class ContentBlock(blocks.StreamBlock):
    heading = blocks.CharBlock(classname="full title")
    paragraph = blocks.RichTextBlock()
    code = CodeBlock(icon="code")
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


class PlaceholderRequest:
    """Just a fake request to please the serve method"""

    is_preview = False
    headers: dict[str, str] = {}
    META: dict = {}
    port = 80
    host = f"https://localhost:{port}"

    def get_host(self):
        return self.host

    def get_port(self):
        return self.port


class Post(Page):
    uuid = models.UUIDField(default=uuid.uuid4, editable=False)
    visible_date = models.DateTimeField(default=timezone.now)
    comments_enabled = models.BooleanField(
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
        ],
        use_json_field=True,
    )

    search_fields = Page.search_fields + [
        index.SearchField("body"),
    ]

    content_panels = Page.content_panels + [
        FieldPanel("visible_date"),
        FieldPanel("body"),
    ]
    template = "cast/post.html"
    body_template = "cast/post_body.html"
    parent_page_types = ["cast.Blog", "cast.Podcast"]

    # managers
    objects = PageManager()

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

    def __str__(self):
        return self.title

    def get_enclosure_url(self, audio_format):
        return getattr(self.podcast_audio, audio_format).url

    def get_enclosure_size(self, audio_format: str) -> int:
        return self.podcast_audio.get_file_size(audio_format)

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
        audios_count = 0
        try:
            audios_count = self.audios.count()
        except ValueError:
            # will be raised on wagtail preview because page_ptr is not set
            pass
        if self.audio_in_body or audios_count > 0:
            return True
        else:
            if isinstance(self.specific, Episode):
                return self.specific.podcast_audio is not None
            else:
                return False

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

    def get_description(self, request=PlaceholderRequest(), render_detail=False, escape_html=True) -> SafeText:
        """
        Get a description for the feed or twitter player card. Needs to be
        a method because the feed is able to pass the actual request object.
        """
        self.template = self.body_template
        description = self.serve(request, render_detail=render_detail).rendered_content.replace("\n", "")
        if escape_html:
            description = escape(description)
        return description

    def save(self, *args, **kwargs):
        save_return = super().save(*args, **kwargs)
        self.sync_media_ids()
        return save_return


class Episode(Post):  # type: ignore
    podcast_audio = models.ForeignKey(
        "cast.Audio", null=True, blank=True, on_delete=models.SET_NULL, related_name="episodes"
    )
    keywords = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=_(
            """A comma-demlimitedlist of up to 12 words for iTunes
            searches. Perhaps include misspellings of the title."""
        ),
    )
    EXPLICIT_CHOICES = ((1, _("yes")), (2, _("no")), (3, _("clean")))
    explicit = models.PositiveSmallIntegerField(
        choices=EXPLICIT_CHOICES,
        help_text=_("``Clean`` will put the clean iTunes graphic by it."),
        default=1,
    )
    block = models.BooleanField(
        default=False,
        help_text=_(
            "Check to block this episode from iTunes because <br />its "
            "content might cause the entire show to be <br />removed from iTunes."
            ""
        ),
    )

    template = "cast/episode.html"
    parent_page_types = ["cast.Podcast"]

    content_panels = Page.content_panels + [
        FieldPanel("visible_date"),
        FieldPanel("body"),
        FieldPanel("keywords"),
        FieldPanel("explicit"),
        FieldPanel("block"),
        FieldPanel("podcast_audio"),
    ]

    def get_context(self, request, *args, **kwargs) -> dict:
        context = super().get_context(request, *args, **kwargs)
        context["episode"] = self
        if hasattr(request, "build_absolute_uri"):
            player_url = reverse(
                "cast:twitter-player", kwargs={"episode_slug": self.slug, "blog_slug": self.podcast.slug}
            )
            player_url = request.build_absolute_uri(player_url)
            context["player_url"] = player_url
        return context

    @property
    def podcast(self):
        """
        The get_parent() method returns wagtail parent page, which is not
        necessarily a Blog model, but maybe the root page. If it's a Blog
        it has a .blog attribute containing the model which has all the
        attributes like blog.comments_enabled etc..
        """
        return self.get_parent().specific


class HomePage(Page):
    body = StreamField(
        [
            ("heading", blocks.CharBlock(classname="full title")),
            ("paragraph", blocks.RichTextBlock()),
            ("image", ImageChooserBlock(template="cast/image/image.html")),
            ("gallery", GalleryBlock(ImageChooserBlock())),
        ],
        use_json_field=True,
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
        FieldPanel("body"),
    ]

    def serve(self, request):
        if self.alias_for_page is not None:
            return redirect(self.alias_for_page.url, permanent=False)
        return super().serve(request)
