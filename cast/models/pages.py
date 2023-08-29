import logging
import uuid
from typing import TYPE_CHECKING, Any, Optional, Union

from django import forms
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import smart_str
from django.utils.html import escape
from django.utils.safestring import SafeText
from django.utils.translation import gettext_lazy as _
from django_comments import get_model as get_comment_model
from modelcluster.contrib.taggit import ClusterTaggableManager
from modelcluster.fields import ParentalKey, ParentalManyToManyField
from slugify import slugify
from taggit.models import TaggedItemBase
from wagtail import blocks
from wagtail.admin.forms import WagtailAdminPageForm
from wagtail.admin.panels import FieldPanel, MultiFieldPanel
from wagtail.api import APIField
from wagtail.embeds.blocks import EmbedBlock
from wagtail.fields import StreamField
from wagtail.images.blocks import ImageChooserBlock
from wagtail.images.models import Image
from wagtail.models import Page, PageManager
from wagtail.search import index

from cast import appsettings
from cast.blocks import AudioChooserBlock, CodeBlock, GalleryBlock, VideoChooserBlock
from cast.models import get_or_create_gallery

from .theme import TemplateBaseDirectory

if TYPE_CHECKING:
    from .index_pages import Blog, ContextDict, Podcast

logger = logging.getLogger(__name__)


comment_model = get_comment_model()


class ContentBlock(blocks.StreamBlock):
    heading: blocks.CharBlock = blocks.CharBlock(classname="full title")
    paragraph: blocks.RichTextBlock = blocks.RichTextBlock()
    code: CodeBlock = CodeBlock(icon="code")
    image: ImageChooserBlock = ImageChooserBlock(template="cast/image/image.html")
    gallery: GalleryBlock = GalleryBlock(ImageChooserBlock())
    embed: EmbedBlock = EmbedBlock()
    video: VideoChooserBlock = VideoChooserBlock(template="cast/video/video.html", icon="media")
    audio: AudioChooserBlock = AudioChooserBlock(template="cast/audio/audio.html", icon="media")

    class Meta:
        icon = "form"


TypeToIdSet = dict[str, set[int]]


def sync_media_ids(from_database: TypeToIdSet, from_body: TypeToIdSet) -> tuple[TypeToIdSet, TypeToIdSet]:
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
    port: int = 80
    host: str = f"https://localhost:{port}"

    def get_host(self) -> str:
        return self.host

    def get_port(self) -> int:
        return self.port


class PostTag(TaggedItemBase):
    content_object = ParentalKey("Post", related_name="tagged_items", on_delete=models.CASCADE)


class Post(Page):
    uuid = models.UUIDField(default=uuid.uuid4, editable=False)
    visible_date = models.DateTimeField(
        default=timezone.now,
        help_text=_("The visible date of the post which is used for sorting."),
        db_index=True,
    )
    comments_enabled = models.BooleanField(
        default=True,
        help_text=_("Whether comments are enabled for this post."),
    )

    images = models.ManyToManyField(Image, blank=True)
    videos = models.ManyToManyField("cast.Video", blank=True)
    galleries = models.ManyToManyField("cast.Gallery", blank=True)
    audios = models.ManyToManyField("cast.Audio", blank=True)
    categories = ParentalManyToManyField("cast.PostCategory", blank=True)

    # managers
    objects: PageManager = PageManager()
    tags = ClusterTaggableManager(through=PostTag, blank=True, verbose_name=_("tags"))

    _local_template_name: Optional[str] = None

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

    api_fields = [
        APIField("uuid"),
        APIField("visible_date"),
        APIField("comments_are_enabled"),
        APIField("body"),
        APIField("html_overview"),
        APIField("html_detail"),
        APIField("comments"),
        APIField("comments_security_data"),
        APIField("podlove_players"),
    ]

    content_panels = Page.content_panels + [
        FieldPanel("visible_date"),
        FieldPanel("categories", widget=forms.CheckboxSelectMultiple),
        FieldPanel("tags"),
        FieldPanel("body"),
    ]
    parent_page_types = ["cast.Blog", "cast.Podcast"]

    @property
    def media_model_lookup(self) -> dict[str, type[models.Model]]:
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
    def blog(self) -> "Blog":
        """
        The get_parent() method returns wagtail parent page, which is not
        necessarily a Blog model, but maybe the root page. If it's a Blog
        it has a .blog attribute containing the model which has all the
        attributes like blog.comments_enabled etc..
        """
        return self.get_parent().blog

    def get_template_base_dir(self, request: HttpRequest) -> str:
        parent = self.get_parent()
        if parent is not None:
            return parent.blog.get_template_base_dir(request)
        else:
            return TemplateBaseDirectory.for_request(request).name

    def get_template(self, request: HttpRequest, *args, local_template_name: str = "post.html", **kwargs) -> str:
        if self._local_template_name is not None:
            local_template_name = self._local_template_name
        template_base_dir = self.get_template_base_dir(request)
        template = f"cast/{template_base_dir}/{local_template_name}"
        return template

    def __str__(self) -> str:
        return self.title

    def get_slug(self) -> str:
        return slugify(self.title)

    @property
    def media_lookup(self) -> dict[str, dict[int, Any]]:
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
        return {}

    @property
    def media_attr_lookup(self) -> "ContextDict":
        return {
            "image": self.images,
            "video": self.videos,
            "gallery": self.galleries,
            "audio": self.audios,
        }

    @property
    def audio_in_body(self) -> bool:
        audio_blocks = []
        for block in self.body:
            for content_block in block.value:
                if content_block.block_type == "audio":
                    audio_blocks.append(content_block)
        return len(audio_blocks) > 0

    @property
    def has_audio(self) -> bool:
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
    def comments_are_enabled(self) -> bool:
        return appsettings.CAST_COMMENTS_ENABLED and self.blog.comments_enabled and self.comments_enabled

    @property
    def comments_security_data(self) -> dict[str, Union[str, int]]:
        from django_comments.forms import CommentSecurityForm

        form = CommentSecurityForm(self)
        return form.generate_security_data()

    @property
    def page_type(self) -> str:
        """
        cannot use wagtail.api.v2.serializers.TypeField.to_representation easily
        """
        return type(self)._meta.app_label + "." + type(self).__name__  # FIXME butt ugly

    def get_context(self, request: HttpRequest, **kwargs) -> "ContextDict":
        context = super().get_context(request, **kwargs)
        context["render_detail"] = kwargs.get("render_detail", False)
        # needed for blocks with themed templates
        context["template_base_dir"] = self.get_template_base_dir(request)
        context["blog"] = self.blog  # needed for SPA themes
        return context

    @property
    def media_ids_from_db(self) -> TypeToIdSet:
        return {k: set(v) for k, v in self.media_lookup.items()}

    def _media_ids_from_body(self, body: StreamField) -> TypeToIdSet:
        from_body: TypeToIdSet = {}
        for content_block in body:
            for block in content_block.value:
                if block.block_type == "gallery":
                    image_ids = [i.id for i in block.value]
                    media_model = get_or_create_gallery(image_ids)
                else:
                    media_model = block.value
                if block.block_type in self.media_model_lookup:
                    if media_model is not None:
                        from_body.setdefault(block.block_type, set()).add(media_model.id)
        return from_body

    @property
    def media_ids_from_body(self) -> TypeToIdSet:
        return self._media_ids_from_body(self.body)

    def sync_media_ids(self) -> None:
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

    @property
    def comments(self) -> list[dict[str, Union[int, None, str]]]:
        ctype = ContentType.objects.get_for_model(self)
        site_id = getattr(settings, "SITE_ID", None)
        qs = comment_model.objects.filter(
            content_type=ctype,
            object_pk=smart_str(self.pk),
            site__pk=site_id,
        )

        # The is_public and is_removed fields are implementation details of the
        # built-in comment model's spam filtering system, so they might not
        # be present on a custom comment model subclass. If they exist, we
        # should filter on them.
        field_names = [f.name for f in comment_model._meta.fields]
        if "is_public" in field_names:
            qs = qs.filter(is_public=True)
        if getattr(settings, "COMMENTS_HIDE_REMOVED", True) and "is_removed" in field_names:
            qs = qs.filter(is_removed=False)

        result = []
        for comment in qs:
            result.append(
                {
                    "id": comment.id,
                    "parent": comment.parent_id,
                    "user": comment.user_name,
                    "date": comment.submit_date,
                    "comment": comment.comment,
                }
            )
        return result

    @property
    def podlove_players(self) -> list[tuple[str, str]]:
        """
        Get the podlove player data for posts containing audio elements.
        """
        result = []
        for pk, audio in self.media_lookup["audio"].items():
            element_id = f"#audio_{pk}"
            result.append((element_id, audio.podlove_url))
        return result

    def get_description(
        self, request=PlaceholderRequest(), render_detail=False, escape_html=True, remove_newlines=True
    ) -> SafeText:
        """
        Get a description for the feed or twitter player card. Needs to be
        a method because the feed is able to pass the actual request object.
        """
        self._local_template_name = "post_body.html"
        description = self.serve(request, render_detail=render_detail).rendered_content
        if remove_newlines:
            description = description.replace("\n", "")
        if escape_html:
            description = escape(description)
        return description

    @property
    def html_overview(self) -> SafeText:
        """
        A convenience method to be able to get the rendered html of the overview
        html of the post for the wagtail api. It then is used in the Vue.js theme
        for example.
        """
        return self.get_description(render_detail=False, escape_html=False, remove_newlines=False)

    @property
    def html_detail(self) -> SafeText:
        """
        Just a convenience method to be able to get the rendered html of the
        post overview and detail for the wagtail api. It then is used in the
        Vue.js theme for example.
        """
        return self.get_description(render_detail=True, escape_html=False, remove_newlines=False)

    def get_absolute_url(self) -> str:
        """This is needed for django-fluentcomments."""
        return self.full_url

    def save(self, *args, **kwargs) -> None:
        save_return = super().save(*args, **kwargs)
        self.sync_media_ids()
        return save_return


class CustomEpisodeForm(WagtailAdminPageForm):
    """
    Custom form for Episode to validate the podcast_audio field.

    The reason for this is that the podcast_audio field is not required
    for draft episodes, but it is required for published episodes. So
    we have to check which button was clicked in the admin form.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["action-publish"] = forms.CharField(required=False, widget=forms.HiddenInput())

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean()
        if cleaned_data.get("action-publish") and cleaned_data.get("podcast_audio") is None:
            raise forms.ValidationError({"podcast_audio": _("An episode must have an audio file to be published.")})
        return cleaned_data


class Episode(Post):
    """A podcast episode is just a Post with some additional fields."""

    podcast_audio = models.ForeignKey(
        "cast.Audio",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="episodes",
        help_text=_(
            "The audio file for this episode -if this is not set, the episode will not be included in the feed."
        ),
    )
    keywords = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=_(
            """A comma-delimited-list of up to 12 words for iTunes
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

    parent_page_types = ["cast.Podcast"]

    content_panels = Page.content_panels + [
        FieldPanel("visible_date"),
        FieldPanel("podcast_audio"),
        MultiFieldPanel(
            [FieldPanel("categories", widget=forms.CheckboxSelectMultiple)],
            heading="Categories",
            classname="collapsed",
        ),
        FieldPanel("tags"),
        FieldPanel("body"),
        FieldPanel("keywords"),
        FieldPanel("explicit"),
        FieldPanel("block"),
    ]

    objects: PageManager = PageManager()
    aliases_homepage: Any  # FIXME: why is this needed?
    base_form_class = CustomEpisodeForm

    def get_template(self, request: HttpRequest, *args, **kwargs) -> str:
        """
        Use get_template() from the parent class, but pass a local template name.
        """
        return super().get_template(request, *args, local_template_name="episode.html", **kwargs)

    def get_context(self, request, *args, **kwargs) -> "ContextDict":
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
    def podcast(self) -> "Podcast":
        """
        The get_parent() method returns wagtail parent page, which is not
        necessarily a Blog model, but maybe the root page. If it's a Blog
        it has a .blog attribute containing the model which has all the
        attributes like blog.comments_enabled etc..
        """
        return self.get_parent().specific

    def get_enclosure_url(self, audio_format: str) -> str:
        return getattr(self.podcast_audio, audio_format).url

    def get_enclosure_size(self, audio_format: str) -> int:
        if self.podcast_audio is None:
            return 0
        return self.podcast_audio.get_file_size(audio_format)


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
        Page,
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

    def serve(self, request, *args, **kwargs) -> HttpResponse:
        if self.alias_for_page is not None:
            return redirect(self.alias_for_page.url, permanent=False)
        return super().serve(request, *args, **kwargs)
