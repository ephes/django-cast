import logging
import uuid
from collections.abc import Iterable, Iterator
from copy import copy
from typing import TYPE_CHECKING, Any, Optional, Protocol, cast

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.validators import MinValueValidator
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
from wagtail.admin.panels import FieldPanel, InlinePanel, MultiFieldPanel
from wagtail.api import APIField
from wagtail.fields import StreamField
from wagtail.images.blocks import ImageChooserBlock
from wagtail.images.models import Image, Rendition
from wagtail.models import Page, PageManager
from wagtail.search import index

from cast import appsettings
from cast.player import audio_player_context_flags
from cast.follow_links import get_follow_links
from cast.blocks import (
    CastImageChooserBlock,
    GalleryBlock,
)
from cast.models import get_or_create_gallery
from cast.post_body_blocks import configured_content_blocks, default_content_blocks
from cast.wagtail_panels import EpisodeTranscriptStatusPanel

from ..views import HtmxHttpRequest
from .image_renditions import ImagesWithType, create_missing_renditions_for_posts
from .repository import (
    AudioById,
    EpisodeFeedContext,
    ImageById,
    LinkTuples,
    PostDetailContext,
    VideoById,
)
from .theme import TemplateBaseDirectory

if TYPE_CHECKING:
    from .contributors import EpisodeContributor
    from .index_pages import Blog, ContextDict, Podcast
    from .transcript import Transcript

logger = logging.getLogger(__name__)


comment_model = get_comment_model()
user_model = get_user_model()
SOCIAL_COVER_RENDITION_SPEC = "fill-1200x630|format-jpeg|jpegquality-75"
PODLOVE_POSTER_RENDITION_SPEC = "max-512x512|format-webp"


class ContentBlock(blocks.StreamBlock):
    def __init__(self, *, section: str, **kwargs: Any) -> None:
        self.section = section
        super().__init__(default_content_blocks() + configured_content_blocks(section), **kwargs)

    def deconstruct(self) -> tuple[str, list[Any], dict[str, str]]:
        return ("cast.models.pages.ContentBlock", [], {"section": self.section})

    def deconstruct_with_lookup(self, lookup: Any) -> tuple[str, list[Any], dict[str, str]]:
        return self.deconstruct()

    @classmethod
    def construct_from_lookup(cls, lookup: Any, *args: Any, **kwargs: Any) -> "ContentBlock":
        return cls(*args, **kwargs)

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
        render_for_feed = True
        request = self.context.get("request")
        if request is not None:
            raw_value = getattr(request, "GET", {}).get("render_for_feed")
            if raw_value is not None:
                render_for_feed = str(raw_value).lower() not in {"0", "false", "no"}
        return post.get_description(
            request=self.context["request"],
            render_detail=self.render_detail,
            render_for_feed=render_for_feed,
            escape_html=False,
            remove_newlines=False,
        )


class CoverImagePosterField(Field):
    """
    Serializer field that returns an absolute URL for the Podlove poster rendition.
    """

    def to_representation(self, post: "Post") -> str:
        request = self.context.get("request")
        blog = post.blog if hasattr(post, "blog") else None
        return post.get_cover_image_poster_url(request=request, blog=blog)


class HasPostDetails(Protocol):
    post_id: int
    template_base_dir: str
    blog: "Blog"
    root_nav_links: LinkTuples
    comments_are_enabled: bool
    has_audio: bool
    page_url: str
    absolute_page_url: str
    owner_username: str
    blog_url: str
    cover_image_url: str
    cover_alt_text: str
    audio_by_id: AudioById
    video_by_id: VideoById
    image_by_id: ImageById
    episode_contributors: list[Any] | None


class Post(Page):
    uuid: models.UUIDField = models.UUIDField(default=uuid.uuid4, editable=False)
    visible_date: models.DateTimeField = models.DateTimeField(
        default=timezone.now,
        help_text=_("The visible date of the post which is used for sorting."),
        db_index=True,
    )
    comments_enabled: models.BooleanField = models.BooleanField(
        default=True,
        help_text=_("Whether comments are enabled for this post."),
    )
    cover_image: models.ForeignKey[Image | None] = models.ForeignKey(
        Image,
        help_text=_("An optional cover image."),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    cover_alt_text: models.CharField = models.CharField(max_length=255, blank=True, default="")

    images: models.ManyToManyField = models.ManyToManyField(Image, blank=True)  # FIXME mypy are you ok?
    videos: models.ManyToManyField = models.ManyToManyField("cast.Video", blank=True)
    galleries: models.ManyToManyField = models.ManyToManyField("cast.Gallery", blank=True)
    audios: models.ManyToManyField = models.ManyToManyField("cast.Audio", blank=True)
    categories = ParentalManyToManyField("cast.PostCategory", blank=True)

    # managers
    tags = ClusterTaggableManager(through=PostTag, blank=True, verbose_name=_("tags"))

    _local_template_name: str | None = None
    _blog: Optional["Blog"] = None
    _media_lookup: dict[str, dict[int, Any]] | None = None

    # wagtail
    body = StreamField(
        [
            ("overview", ContentBlock(section="overview")),
            ("detail", ContentBlock(section="detail")),
        ],
        use_json_field=True,
    )

    search_fields = Page.search_fields + [
        index.SearchField("body"),
        index.SearchField("cover_alt_text"),
    ]

    api_fields = [
        APIField("uuid"),
        APIField("visible_date"),
        APIField("comments_are_enabled"),
        APIField("cover_image"),
        APIField("cover_alt_text"),
        APIField("cover_image_poster_url", serializer=CoverImagePosterField(source="*")),
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
        MultiFieldPanel(
            [
                FieldPanel("cover_image"),
                FieldPanel("cover_alt_text"),
            ],
            heading="Cover Image",
            classname="collapsed",
            help_text=_(
                "The cover image for this post. It will be used in the feed, "
                "in the twitter card and maybe on the blog index page."
            ),
        ),
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
        if self._blog is None:
            self._blog = self.get_parent().blog
        return self._blog

    def get_template_base_dir(self, request: HttpRequest) -> str:
        if self._blog is not None:
            return self._blog.get_template_base_dir(cast(HtmxHttpRequest, request))
        parent = self.get_parent()
        if parent is None:
            return TemplateBaseDirectory.for_request(request).name
        self._blog = parent.blog
        return self._blog.get_template_base_dir(cast(HtmxHttpRequest, request))

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
        if self._media_lookup is not None:
            return self._media_lookup
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
        repository = getattr(self, "_repository", None)
        if repository is not None and hasattr(repository, "comments_are_enabled"):
            return repository.comments_are_enabled
        return self.get_comments_are_enabled(self.blog)

    @property
    def comments_security_data(self) -> dict[str, str | int]:
        from cast.comments.utils import comments_are_open
        from django_comments.forms import CommentSecurityForm

        if not comments_are_open(self):
            return {}
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

    def get_full_url(self, request=None):
        if hasattr(self, "page_url"):
            return self.page_url
        return super().get_full_url(request=request)

    def get_updated_timestamp(self) -> int:
        """Use the last_published_at timestamp if available, otherwise the visible_date."""
        if self.last_published_at is not None:
            return int(self.last_published_at.timestamp())
        else:
            return int(self.visible_date.timestamp())

    @staticmethod
    def get_context_from_repository(context: "ContextDict", repository: HasPostDetails) -> "ContextDict":
        context["template_base_dir"] = repository.template_base_dir
        blog = repository.blog
        context["blog"] = blog
        context["comments_are_enabled"] = repository.comments_are_enabled
        context["root_nav_links"] = repository.root_nav_links
        context["has_audio"] = repository.has_audio
        context.update(audio_player_context_flags(enabled=repository.has_audio))
        context["page_url"] = repository.page_url
        context["absolute_page_url"] = repository.absolute_page_url
        context["owner_username"] = repository.owner_username
        context["blog_url"] = repository.blog_url
        context["cover_image_url"] = repository.cover_image_url
        context["cover_alt_text"] = repository.cover_alt_text
        context["audio_items"] = list(repository.audio_by_id.items())
        if (episode_contributors := getattr(repository, "episode_contributors", None)) is not None:
            context["episode_contributors"] = episode_contributors
        if context["page"].pk is None:
            context["page"].pk = repository.post_id
        return context

    def get_context(self, request: HttpRequest, **kwargs) -> "ContextDict":
        context = super().get_context(request, **kwargs)
        request = cast(HtmxHttpRequest, request)
        context["repository"] = repository = self.get_repository(request, kwargs)
        context["render_detail"] = kwargs.get("render_detail", False)
        context["render_for_feed"] = kwargs.get("render_for_feed", False)
        context["updated_timestamp"] = self.get_updated_timestamp()
        context = self.get_context_from_repository(context, repository)
        context_page = copy(self)
        context_page.owner = user_model(username=context["owner_username"])
        if context["render_for_feed"]:
            # use absolute urls for feed
            context_page.page_url = context["absolute_page_url"]
        else:
            context_page.page_url = context["page_url"]
        context["page"] = context_page
        context["self"] = context_page
        context.update(self.get_cover_image_context(context, blog=context["blog"]))
        context.update(self.get_social_cover_image_context(request=request, blog=context["blog"]))
        # Enable theme selector on post detail pages
        context["has_selectable_themes"] = True
        context["follow_links"] = get_follow_links(context.get("blog"))
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
                        if isinstance(image, dict) and "value" in image:
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
                            media_model_class = self.media_model_lookup[block.block_type]
                            if media_model_class._default_manager.filter(pk=media_model).exists():
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

    def get_all_images(self) -> ImagesWithType:
        """
        Use it like this:
        posts_queryset = Post.objects.prefetch_related("images", "galleries__images")[:10]
        for post in posts_queryset:
            for image_type, image in post.get_all_images():
                print(image_type, image)
        """
        try:
            for image in self.images.all():
                yield "regular", image
            for gallery in self.galleries.all():
                for image in gallery.images.all():
                    yield "gallery", image
        except ValueError:
            # will be raised on wagtail preview because page_ptr is not set
            pass

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
        for pk, audio in self.media_lookup.get("audio", {}).items():
            element_id = f"#audio_{pk}"
            result.append((element_id, audio.get_podlove_url(self.pk)))
        return result

    @staticmethod
    def get_cover_image_context(context: "ContextDict", blog: Optional["Blog"]) -> dict[str, str]:
        if (
            cover_image_url_from_post := context.get("cover_image_url")
        ) is not None and cover_image_url_from_post != "":
            # if the cover image is set in the context, use it
            return {"cover_image_url": cover_image_url_from_post, "cover_alt_text": context.get("cover_alt_text", "")}
        if blog is not None:
            return blog.get_cover_image_context()

        # no cover image set
        return {"cover_image_url": "", "cover_alt_text": ""}

    def get_social_cover_image_context(self, *, request: HttpRequest, blog: Optional["Blog"]) -> dict[str, str | int]:
        cover_image = self.cover_image
        if cover_image is None and blog is not None:
            cover_image = blog.cover_image
        if cover_image is None:
            return {
                "social_cover_image_url": "",
                "social_cover_image_width": "",
                "social_cover_image_height": "",
            }
        cover_image = cast(Image, cover_image)
        rendition = cover_image.get_rendition(SOCIAL_COVER_RENDITION_SPEC)
        cover_url = rendition.url
        if hasattr(request, "build_absolute_uri"):
            cover_url = request.build_absolute_uri(cover_url)
        return {
            "social_cover_image_url": cover_url,
            "social_cover_image_width": rendition.width,
            "social_cover_image_height": rendition.height,
        }

    def get_cover_image_poster_url(self, *, request: HttpRequest | None, blog: Optional["Blog"]) -> str:
        cover_image = self.cover_image
        if cover_image is None and blog is not None:
            cover_image = blog.cover_image
        if cover_image is None:
            return ""
        cover_image = cast(Image, cover_image)
        rendition = cover_image.get_rendition(PODLOVE_POSTER_RENDITION_SPEC)
        poster_url = rendition.url
        if request is not None and hasattr(request, "build_absolute_uri"):
            poster_url = request.build_absolute_uri(poster_url)
        return poster_url

    def get_description(
        self,
        *,
        request: HttpRequest,
        render_detail: bool = False,
        render_for_feed: bool = True,
        escape_html: bool = True,
        remove_newlines: bool = True,
        repository: PostDetailContext | None = None,
    ) -> SafeText:
        """
        Get a description for the feed or twitter player card. Needs to be
        a method because the feed is able to pass the actual request object.
        """
        request = cast(HtmxHttpRequest, request)
        if repository is None:
            repository = self.get_repository(request, {})
        self._local_template_name = "post_body.html"
        description = self.serve(
            request, render_detail=render_detail, repository=repository, render_for_feed=render_for_feed
        ).rendered_content
        if remove_newlines:
            description = description.replace("\n", "")
        if escape_html:
            description = escape(description)
        return description

    def get_absolute_url(self) -> str:
        """This is needed for django-fluentcomments."""
        return self.full_url

    def get_site(self):
        if hasattr(self, "_repository"):
            return self._repository.site
        return super().get_site()

    def get_repository(self, request: HtmxHttpRequest, kwargs: dict[str, Any]) -> PostDetailContext:
        repository = kwargs.get("repository")
        if repository is not None:
            return repository
        return PostDetailContext.create_from_django_models(request=request, post=self)

    def serve(self, request: HtmxHttpRequest, *args, **kwargs):
        kwargs.setdefault("render_detail", True)
        kwargs["repository"] = repository = self.get_repository(request, kwargs)
        # set the template_base_dir from the post_data to avoid having self.get_template_base_dir() called
        kwargs["template_base_dir"] = repository.template_base_dir
        return super().serve(request, *args, **kwargs)

    def get_preview_context(self, request, mode_name):
        return self.get_context(request, render_detail=True, is_preview=True)

    def serve_preview(self, request, mode_name, *args, **kwargs):
        # sync media ids before preview, because otherwise the repository
        # will not have the correct media ids and fail to get the correct
        # renditions and fail with a w1110 not found rendition key error.
        try:
            self.sync_media_ids()  # raises ValueError
            create_missing_renditions_for_posts(iter([self]))  # needed for images src / srcset in preview
        except ValueError:
            # will be raised on wagtail preview because page_ptr is not set
            pass
        return super().serve_preview(request, mode_name)

    def save(self, *args, **kwargs) -> None:
        save_return = super().save(*args, **kwargs)
        self.sync_media_ids()
        create_missing_renditions_for_posts(iter([self]))  # needed for images src / srcset
        return save_return


class CustomEpisodeForm(WagtailAdminPageForm):
    """
    Custom form for Episode to validate the podcast_audio field.

    The reason for this is that the podcast_audio field is not required
    for draft episodes, but it is required for published episodes. So
    we have to check which button was clicked in the admin form.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self.parent_page is not None:
            self.instance._blog = cast("Blog", self.parent_page.specific)
        season_field = self.fields.get("season")
        if season_field is None:
            return
        try:
            parent_podcast_id = self.instance.blog.pk
        except (AttributeError, ObjectDoesNotExist, ValueError):
            parent_podcast_id = None
        if parent_podcast_id is not None:
            season_field.queryset = season_field.queryset.filter(podcast_id=parent_podcast_id)

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean()
        action_publish_values = self.data.getlist("action-publish") if hasattr(self.data, "getlist") else []
        publish_requested = any(action_publish_values) or bool(self.data.get("action-publish"))
        if publish_requested and cleaned_data.get("podcast_audio") is None:
            raise forms.ValidationError({"podcast_audio": _("An episode must have an audio file to be published.")})
        return cleaned_data


class Episode(Post):
    """A podcast episode is just a Post with some additional fields."""

    class EpisodeType(models.TextChoices):
        FULL = "full", _("Full")
        TRAILER = "trailer", _("Trailer")
        BONUS = "bonus", _("Bonus")

    podcast_audio: models.ForeignKey = models.ForeignKey(
        "cast.Audio",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="episodes",
        help_text=_(
            "The audio file for this episode -if this is not set, the episode will not be included in the feed."
        ),
    )
    keywords: models.CharField = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=_(
            """A comma-delimited-list of up to 12 words for iTunes
            searches. Perhaps include misspellings of the title."""
        ),
    )
    EXPLICIT_CHOICES = ((1, _("yes")), (2, _("no")), (3, _("clean")))
    explicit: models.PositiveSmallIntegerField = models.PositiveSmallIntegerField(
        choices=EXPLICIT_CHOICES,
        help_text=_("``Clean`` will put the clean iTunes graphic by it."),
        default=1,
    )
    block: models.BooleanField = models.BooleanField(
        default=False,
        help_text=_(
            "Check to block this episode from iTunes because <br />its "
            "content might cause the entire show to be <br />removed from iTunes."
            ""
        ),
    )
    episode_number: models.PositiveIntegerField = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text=_("Optional positive episode number used as podcast publishing metadata."),
    )
    episode_type: models.CharField = models.CharField(
        max_length=16,
        choices=EpisodeType.choices,
        blank=True,
        default="",
        help_text=_("Optional podcast episode type. Leave blank to omit the feed tag; blank is equivalent to full."),
    )
    season: models.ForeignKey = models.ForeignKey(
        "cast.Season",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text=_("Optional podcast season. It must belong to this episode's podcast."),
    )

    parent_page_types = ["cast.Podcast"]

    content_panels = Page.content_panels + [
        FieldPanel("visible_date"),
        FieldPanel("podcast_audio"),
        EpisodeTranscriptStatusPanel(heading=_("Transcript generation")),
        MultiFieldPanel(
            [
                FieldPanel("episode_type"),
                FieldPanel("episode_number"),
                FieldPanel("season"),
            ],
            heading=_("Podcast publishing metadata"),
            classname="collapsed",
            help_text=_(
                "Podcast clients identify feed items by GUID. Episode numbers, types, and seasons are "
                "publishing metadata only."
            ),
        ),
        MultiFieldPanel(
            [FieldPanel("categories", widget=forms.CheckboxSelectMultiple)],
            heading="Categories",
            classname="collapsed",
        ),
        FieldPanel("tags"),
        MultiFieldPanel(
            [
                FieldPanel("cover_image"),
                FieldPanel("cover_alt_text"),
            ],
            heading="Cover Image",
            classname="collapsed",
            help_text=_(
                "The cover image for this episode. It will be used in the podcast feed, "
                "in the twitter player card and maybe on the blog index page."
            ),
        ),
        FieldPanel("body"),
        FieldPanel("keywords"),
        FieldPanel("explicit"),
        FieldPanel("block"),
        MultiFieldPanel(
            [InlinePanel("contributor_assignments", label=_("Contributor"))],
            heading=_("Contributors"),
            classname="collapsed",
        ),
    ]

    objects: PageManager = PageManager()
    aliases_homepage: Any  # FIXME: why is this needed?
    base_form_class = CustomEpisodeForm
    # Per-instance repository cache; snapshots/deserializers overwrite this on episode instances.
    _visible_contributor_assignments: list["EpisodeContributor"] | None = None

    def get_template(self, request: HttpRequest, *args, **kwargs) -> str:
        """
        Use get_template() from the parent class, but pass a local template name.
        """
        return super().get_template(request, *args, local_template_name="episode.html", **kwargs)

    def clean(self) -> None:
        super().clean()
        self._validate_season_matches_podcast()

    def _validate_season_matches_podcast(self) -> None:
        if self.season_id is None:
            return
        try:
            parent_podcast_id = self.blog.pk
        except (AttributeError, ObjectDoesNotExist, ValueError):
            return
        if parent_podcast_id is None:
            return
        if self.season.podcast_id != parent_podcast_id:
            raise ValidationError({"season": _("The selected season must belong to this episode's podcast.")})

    def get_context(self, request, **kwargs) -> "ContextDict":
        context = super().get_context(request, **kwargs)
        context["episode"] = self
        if "episode_contributors" not in context:
            context["episode_contributors"] = self.visible_contributor_assignments
        repository = context.get("repository")
        podcast = context.get("blog")
        if podcast is None and repository is not None and hasattr(repository, "blog"):
            podcast = repository.blog
        if podcast is None:
            podcast = self.podcast
        cover_image_context = self.get_cover_image_context(context, podcast)
        context.update(cover_image_context)
        include_public_transcript_url = (
            not kwargs.get("is_preview") and not context.get("render_for_feed") and self.has_transcript
        )
        if hasattr(request, "build_absolute_uri"):
            blog_slug = podcast.slug if podcast is not None else self.blog.slug
            player_url = reverse("cast:twitter-player", kwargs={"episode_slug": self.slug, "blog_slug": blog_slug})
            player_url = request.build_absolute_uri(player_url)
            context["player_url"] = player_url
            if include_public_transcript_url:
                transcript_url = reverse(
                    "cast:episode-transcript",
                    kwargs={"episode_slug": self.slug, "blog_slug": blog_slug},
                )
                context["episode_transcript_url"] = request.build_absolute_uri(transcript_url)
        elif include_public_transcript_url:
            blog_slug = podcast.slug if podcast is not None else self.blog.slug
            context["episode_transcript_url"] = reverse(
                "cast:episode-transcript",
                kwargs={"episode_slug": self.slug, "blog_slug": blog_slug},
            )
        return context

    @property
    def podcast(self) -> Optional["Podcast"]:
        """
        The get_parent() method returns wagtail parent page, which is not
        necessarily a Blog model, but maybe the root page. If it's a Blog
        it has a .blog attribute containing the model which has all the
        attributes like blog.comments_enabled etc.
        """
        parent = self.get_parent()
        if parent is not None:
            return parent.specific
        return None

    @property
    def visible_contributor_assignments(self) -> list["EpisodeContributor"]:
        assignments = self._visible_contributor_assignments
        if assignments is not None:
            return assignments
        prefetched_assignments = getattr(self, "_prefetched_objects_cache", {}).get("contributor_assignments")
        if prefetched_assignments is not None:
            assignments_iterable = prefetched_assignments
        else:
            try:
                assignments_iterable = self.contributor_assignments.select_related("contributor__avatar", "link").all()
            except ValueError:
                return []
        return [
            assignment
            for assignment in assignments_iterable
            if assignment.contributor_id is not None and assignment.contributor.visible
        ]

    def get_enclosure_url(self, audio_format: str) -> str:
        return getattr(self.podcast_audio, audio_format).url

    def get_enclosure_size(self, audio_format: str) -> int:
        if self.podcast_audio is None:
            return 0
        from .audio import Audio

        return cast(Audio, self.podcast_audio).get_file_size(audio_format)

    def get_transcript_or_none(self, repository: EpisodeFeedContext | None = None) -> Optional["Transcript"]:
        if repository is not None:
            podcast_audio, transcript = repository.podcast_audio, repository.transcript
        else:
            podcast_audio = self.podcast_audio  # type: ignore
            try:
                transcript = podcast_audio.transcript
            except (ObjectDoesNotExist, AttributeError):
                transcript = None
        return transcript

    @property
    def transcript(self) -> Optional["Transcript"]:
        return self.get_transcript_or_none()

    @property
    def has_transcript(self) -> bool:
        return self.transcript is not None

    def get_transcript_url(self) -> str:
        return reverse("cast:episode-transcript", kwargs={"blog_slug": self.blog.slug, "episode_slug": self.slug})

    def get_vtt_transcript_url(self, request: HtmxHttpRequest, repository: EpisodeFeedContext | None) -> str | None:
        if (transcript := self.get_transcript_or_none(repository)) is not None:
            if transcript.vtt is not None:
                relative_url = reverse("cast:webvtt-transcript", kwargs={"pk": transcript.pk})
                relative_url = f"{relative_url}?episode_id={self.pk}"
                return request.build_absolute_uri(relative_url)
        return None

    @property
    def podlove_players(self) -> list[tuple[str, str]]:
        players = super().podlove_players
        podcast_audio = self.podcast_audio
        if podcast_audio is None:
            return players
        from .audio import Audio

        podcast_audio = cast(Audio, podcast_audio)
        if podcast_audio.pk is None:
            return players
        if podcast_audio.pk in self.media_lookup.get("audio", {}):
            return players
        element_id = f"#audio_{podcast_audio.pk}"
        players.append((element_id, podcast_audio.get_podlove_url(self.pk)))
        return players

    def get_podcastindex_transcript_url(self, request: HtmxHttpRequest, repository: EpisodeFeedContext) -> str | None:
        if (transcript := self.get_transcript_or_none(repository)) is not None:
            if transcript.dote is not None:
                relative_url = reverse("cast:podcastindex-transcript-json", kwargs={"pk": transcript.pk})
                relative_url = f"{relative_url}?episode_id={self.pk}"
                return request.build_absolute_uri(relative_url)
        return None


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
    alias_for_page: models.ForeignKey = models.ForeignKey(
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
            return redirect(cast(Page, self.alias_for_page).url, permanent=False)
        return super().serve(request, *args, **kwargs)
