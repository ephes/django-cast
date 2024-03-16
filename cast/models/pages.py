import logging
import uuid
from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING, Any

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
from rest_framework.fields import Field
from slugify import slugify
from taggit.models import TaggedItemBase
from wagtail import blocks
from wagtail.admin.forms import WagtailAdminPageForm
from wagtail.admin.panels import FieldPanel, MultiFieldPanel
from wagtail.api import APIField
from wagtail.embeds.blocks import EmbedBlock
from wagtail.fields import StreamField
from wagtail.images.blocks import ImageChooserBlock
from wagtail.images.models import Image, Rendition
from wagtail.models import Page, PageManager
from wagtail.search import index

from cast import appsettings
from cast.blocks import (
    AudioChooserBlock,
    CastImageChooserBlock,
    CodeBlock,
    GalleryBlock,
    GalleryBlockWithLayout,
    VideoChooserBlock,
)
from cast.models import get_or_create_gallery

from ..cache import PostData
from ..renditions import ImageType, RenditionFilters
from .theme import TemplateBaseDirectory

if TYPE_CHECKING:
    from .index_pages import Blog, ContextDict, Podcast

logger = logging.getLogger(__name__)


comment_model = get_comment_model()


class ContentBlock(blocks.StreamBlock):
    heading: blocks.CharBlock = blocks.CharBlock(classname="full title")
    paragraph: blocks.RichTextBlock = blocks.RichTextBlock()
    code: CodeBlock = CodeBlock(icon="code")
    image: CastImageChooserBlock = CastImageChooserBlock(template="cast/image/image.html")
    gallery: GalleryBlockWithLayout = GalleryBlockWithLayout()
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


class PostTag(TaggedItemBase):
    content_object = ParentalKey("Post", related_name="tagged_items", on_delete=models.CASCADE)


class HtmlField(Field):
    """
    A serializer field to render the html of a post. It's used in the wagtail api
    to get the rendered html of the overview and detail of a post. An SPA theme
    like `cast_vue` can then use this html instead of having to render the blocks
    itself.
    """

    def __init__(self, *, render_detail: bool = False, **kwargs) -> None:
        self.render_detail = render_detail
        super().__init__(**kwargs)

    def to_representation(self, post: "Post") -> SafeText:
        """
        Pass the request from context to the post's serve method to be able to
        render the post with the correct theme.
        """
        return post.get_description(
            request=self.context["request"], render_detail=self.render_detail, escape_html=False, remove_newlines=False
        )


ImagesWithType = Iterator[tuple[ImageType, Image]]


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

    images: models.ManyToManyField = models.ManyToManyField(Image, blank=True)  # FIXME mypy are you ok?
    videos: models.ManyToManyField = models.ManyToManyField("cast.Video", blank=True)
    galleries: models.ManyToManyField = models.ManyToManyField("cast.Gallery", blank=True)
    audios: models.ManyToManyField = models.ManyToManyField("cast.Audio", blank=True)
    categories = ParentalManyToManyField("cast.PostCategory", blank=True)

    # managers
    tags = ClusterTaggableManager(through=PostTag, blank=True, verbose_name=_("tags"))

    _local_template_name: str | None = None

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
        APIField("html_overview", serializer=HtmlField(source="*", render_detail=False)),
        APIField("html_detail", serializer=HtmlField(source="*", render_detail=True)),
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
        attributes like blog.comments_enabled etc.
        """
        if hasattr(self, "_post_data"):
            return self._post_data.blog
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
        template_base_dir = kwargs.get("template_base_dir", None)
        if template_base_dir is None:
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

    def get_comments_are_enabled(self, blog: "Blog") -> bool:
        return appsettings.CAST_COMMENTS_ENABLED and blog.comments_enabled and self.comments_enabled

    @property
    def comments_are_enabled(self) -> bool:
        return self.get_comments_are_enabled(self.blog)

    @property
    def comments_security_data(self) -> dict[str, str | int]:
        from django_comments.forms import CommentSecurityForm

        form = CommentSecurityForm(self)
        return form.generate_security_data()

    @property
    def page_type(self) -> str:
        """
        cannot use wagtail.api.v2.serializers.TypeField.to_representation easily
        """
        return type(self)._meta.app_label + "." + type(self).__name__  # FIXME butt ugly

    def get_url(self, request=None, current_site=None):
        return super().get_url(request=request, current_site=current_site)

    def get_context_without_database(
        self, request: HttpRequest, context: dict[str, Any], post_data: PostData
    ) -> dict[str, Any]:
        """
        Get the context for the post without any database queries.
        """
        context["template_base_dir"] = post_data.template_base_dir
        blog = post_data.blog
        context["blog"] = blog
        context["comments_are_enabled"] = self.get_comments_are_enabled(blog)
        context["root_nav_links"] = post_data.root_nav_links
        context["has_audio"] = post_data.has_audio_by_id[self.pk]
        context["page_url"] = post_data.page_url_by_id[self.pk]
        context["owner_username"] = post_data.owner_username_by_id[self.pk]
        context["blog_url"] = post_data.blog_url
        context["audio_items"] = post_data.audios_by_post_id.get(self.pk, {}).items()
        request.cast_site_template_base_dir = post_data.template_base_dir  # type: ignore
        return context

    def get_context(self, request: HttpRequest, **kwargs) -> "ContextDict":
        context = super().get_context(request, **kwargs)
        context["render_detail"] = kwargs.get("render_detail", False)
        context["post_data"] = post_data = kwargs.get("post_data", None)
        if post_data is not None:
            return self.get_context_without_database(request, context, post_data)
        # needed for blocks with themed templates
        context["template_base_dir"] = self.get_template_base_dir(request)
        blog = self.blog
        context["comments_are_enabled"] = self.get_comments_are_enabled(blog)
        context["blog"] = blog
        context["root_nav_links"] = [(p.get_url(), p.title) for p in blog.get_root().get_children().live()]
        context["has_audio"] = self.has_audio
        context["page_url"] = self.get_url(request=request)
        if self.owner is not None:
            context["owner_username"] = self.owner.username
        else:
            context["owner_username"] = "unknown"
        context["blog_url"] = blog.get_url(request=request)
        context["audio_items"] = self.media_lookup["audio"].items()
        return context

    @property
    def media_ids_from_db(self) -> TypeToIdSet:
        return {k: set(v) for k, v in self.media_lookup.items()}

    def _media_ids_from_body(self, body: StreamField) -> TypeToIdSet:
        from_body: TypeToIdSet = {}
        for content_block in body:
            for block in content_block.value:
                if block.block_type == "gallery":
                    images = block.value.get("gallery", [])
                    image_ids = []
                    for image in images:
                        if isinstance(image, dict):
                            image_ids.append(image["value"])
                        elif isinstance(image, Image):
                            image_ids.append(image.pk)
                        elif isinstance(image, int):
                            image_ids.append(image)
                    media_model = get_or_create_gallery(image_ids)
                else:
                    media_model = block.value
                if block.block_type in self.media_model_lookup:
                    if media_model is not None:
                        if hasattr(media_model, "id"):
                            from_body.setdefault(block.block_type, set()).add(media_model.id)
                        elif isinstance(media_model, int):
                            from_body.setdefault(block.block_type, set()).add(media_model)
                        else:
                            raise ValueError(f"media model {media_model} is not an instance of int or a model")
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

    # helper methods for image rendition syncing
    @staticmethod
    def get_all_images_from_queryset(posts: Iterable["Post"]) -> ImagesWithType:
        for post in posts:
            yield from post.get_all_images()

    @staticmethod
    def get_all_renditions_from_queryset_flat(posts: Iterable["Post"]) -> Iterator[Rendition]:
        for image_type, image in Post.get_all_images_from_queryset(posts):
            yield from image.renditions.all()

    @staticmethod
    def get_all_renditions_from_queryset(posts: Iterable["Post"]) -> dict[int, list[Rendition]]:
        all_renditions = Post.get_all_renditions_from_queryset_flat(posts)
        renditions_for_posts: dict[int, list[Rendition]] = {}
        for rendition in all_renditions:
            renditions_for_posts.setdefault(rendition.image_id, []).append(rendition)
        return renditions_for_posts

    @staticmethod
    def get_all_filterstrings(images_with_type: ImagesWithType) -> Iterator[tuple[int, str]]:
        for image_type, image in images_with_type:
            rfs = RenditionFilters.from_wagtail_image_with_type(image, image_type)
            for filter_string in rfs.filter_strings:
                yield image.pk, filter_string

    def get_all_images(self) -> ImagesWithType:
        """
        Use it like this:
        posts_queryset = Post.objects.prefetch_related("images", "galleries__images")[:10]
        for post in posts_queryset:
            for image_type, image in post.get_all_images():
                print(image_type, image)
        """
        for image in self.images.all():
            yield "regular", image
        for gallery in self.galleries.all():
            for image in gallery.images.all():
                yield "gallery", image

    @staticmethod
    def get_obsolete_and_missing_rendition_strings(
        images_with_type: ImagesWithType,
    ) -> tuple[set[int], dict[int, set[str]]]:
        """
        Get all obsolete and missing rendition strings from a queryset of posts.
        """
        required_renditions = set(Post.get_all_filterstrings(images_with_type))
        all_image_ids = {image_id for image_id, filter_string in required_renditions}
        renditions_queryset = Rendition.objects.filter(image__in=all_image_ids)
        existing_rendition_to_id = {
            (image_id, filter_spec): pk
            for pk, image_id, filter_spec in renditions_queryset.values_list("pk", "image_id", "filter_spec")
        }
        existing_renditions = set(existing_rendition_to_id.keys())
        obsolete_renditions_unfiltered = existing_renditions - required_renditions

        # remove wagtail generated renditions from obsolete_renditions
        obsolete_renditions = set()
        wagtail_filter_specs = {"max-165x165", "max-800x600"}
        for image_id, filter_spec in obsolete_renditions_unfiltered:
            if filter_spec not in wagtail_filter_specs:
                obsolete_renditions.add((image_id, filter_spec))
        obsolete_rendition_pks = {
            existing_rendition_to_id[(image_id, filter_spec)] for image_id, filter_spec in obsolete_renditions
        }

        # build missing renditions aggregated by image id
        missing_renditions = required_renditions - existing_renditions
        missing_renditions_by_image_id: dict[int, set[str]] = {}  # why mypy?
        for image_id, filter_spec in missing_renditions:
            missing_renditions_by_image_id.setdefault(image_id, set()).add(filter_spec)
        return obsolete_rendition_pks, missing_renditions_by_image_id

    @property
    def comments(self) -> list[dict[str, int | None | str]]:
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
        self,
        *,
        request: HttpRequest,
        render_detail: bool = False,
        escape_html: bool = True,
        remove_newlines: bool = True,
        post_data: PostData | None = None,
    ) -> SafeText:
        """
        Get a description for the feed or twitter player card. Needs to be
        a method because the feed is able to pass the actual request object.
        """
        self._local_template_name = "post_body.html"
        description = self.serve(request, render_detail=render_detail, post_data=post_data).rendered_content
        if remove_newlines:
            description = description.replace("\n", "")
        if escape_html:
            description = escape(description)
        return description

    def get_absolute_url(self) -> str:
        """This is needed for django-fluentcomments."""
        return self.full_url

    def get_site(self):
        if hasattr(self, "_post_data"):
            return self._post_data.site
        return super().get_site()

    def serve(self, request, *args, **kwargs):
        post_data = kwargs.get("post_data", None)
        if post_data is not None:
            # set the template_base_dir from the post_data to avoid having self.get_template_base_dir() called
            self._post_data = post_data
            kwargs["template_base_dir"] = post_data.template_base_dir
            return super().serve(request, *args, **kwargs)
        return super().serve(request, *args, **kwargs)

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

    def get_context(self, request, **kwargs) -> "ContextDict":
        context = super().get_context(request, **kwargs)
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
        attributes like blog.comments_enabled etc.
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
            ("image", CastImageChooserBlock(template="cast/image/image.html")),
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
