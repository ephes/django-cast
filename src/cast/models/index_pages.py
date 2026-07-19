import json
import logging
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from django.core.validators import MinValueValidator
from django.db import models
from django.http.request import QueryDict
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from wagtail.admin.panels import FieldPanel, MultiFieldPanel
from wagtail.api import APIField
from wagtail.fields import RichTextField
from wagtail.images.models import Image
from wagtail.models import Page, PageManager

from cast import appsettings
from cast.blog_index import (
    apply_repository_context,
    cover_image_context,
    create_blog_filterset,
    create_theme_form,
    next_and_previous_pages,
    other_get_params,
    pagination_context,
    present_blog_index_context,
    published_posts_for_index,
    unfiltered_published_posts,
)
from cast.http_types import HtmxHttpRequest
from cast.models.itunes import ItunesArtWork

from .pages import Post
from .repository import BlogIndexContext
from .theme import get_template_base_dir, get_template_base_dir_choices

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from django.core.paginator import Page as DjangoPage
    from django.forms import Form

    from cast.blog_index import PostFilterset


ContextDict = dict[str, Any]


class Season(models.Model):
    """Reusable podcast season metadata scoped to one podcast."""

    podcast: models.ForeignKey = models.ForeignKey(
        "cast.Podcast",
        on_delete=models.CASCADE,
        related_name="seasons",
        help_text=_("Podcast this season belongs to."),
    )
    number: models.PositiveIntegerField = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        help_text=_("Positive season number used in podcast feeds."),
    )
    name: models.CharField = models.CharField(
        max_length=128,
        blank=True,
        default="",
        help_text=_("Optional season name for Podcasting 2.0 feeds."),
    )

    class Meta:
        ordering = ["podcast_id", "number"]
        constraints = [
            models.UniqueConstraint(fields=["podcast", "number"], name="unique_podcast_season_number"),
        ]

    def __str__(self) -> str:
        podcast_title = self.podcast.title if self.podcast_id is not None else _("Podcast")
        label = _("Season %(number)s") % {"number": self.number}
        if self.name:
            return f"{podcast_title}: {label} - {self.name}"
        return f"{podcast_title}: {label}"


class Blog(Page):
    """
    This is the index page for a blog. It contains a list of posts.
    """

    author: models.CharField = models.CharField(
        max_length=255,
        default=None,
        null=True,
        blank=True,
        help_text=_("Freeform text that will be used in the feed."),
    )
    uuid: models.UUIDField = models.UUIDField(default=uuid.uuid4, editable=False)
    email: models.EmailField = models.EmailField(null=True, default=None, blank=True)
    comments_enabled: models.BooleanField = models.BooleanField(
        _("comments_enabled"),
        default=True,
        help_text=_("Whether comments are enabled for this blog."),
    )
    cover_image: models.ForeignKey = models.ForeignKey(
        Image,
        help_text=_("An optional cover image."),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    cover_alt_text: models.CharField = models.CharField(max_length=255, blank=True, default="")
    noindex: models.BooleanField = models.BooleanField(
        "noindex",
        default=False,
        help_text=_(
            "Whether to add a noindex meta tag to this page and all subpages excluding them from search engines."
        ),
    )
    template_base_dir: models.CharField = models.CharField(
        choices=get_template_base_dir_choices(),
        max_length=128,
        default=None,
        null=True,
        blank=True,
        help_text=_(
            "The theme to use for this blog implemented as a template base directory. "
            "If not set, the template base directory will be determined by a site setting."
        ),
    )

    # wagtail
    subtitle: models.CharField = models.CharField(
        verbose_name=_("subtitle"),
        max_length=255,
        default="",
        blank=True,
        help_text=_("The page subtitle as you'd like it to be seen by the public"),
    )
    description = RichTextField(blank=True)
    content_panels = Page.content_panels + [
        FieldPanel("subtitle", classname="collapsed"),
        FieldPanel("description", classname="full"),
        FieldPanel("email"),
        FieldPanel("author"),
        FieldPanel("comments_enabled"),
        FieldPanel("template_base_dir"),
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
    ]
    promote_panels = Page.promote_panels + [
        FieldPanel("noindex"),
    ]
    api_fields = [
        APIField("description"),
    ]

    subpage_types = ["cast.Post"]
    is_podcast = False

    def __str__(self) -> str:
        return self.title

    def get_template_base_dir(self, request: HtmxHttpRequest) -> str:
        return get_template_base_dir(request, self.template_base_dir)

    def get_template(self, request: HtmxHttpRequest, *args: Any, **kwargs: Any) -> str:
        template_base_dir = kwargs.get("template_base_dir", None)
        if template_base_dir is None:
            template_base_dir = self.get_template_base_dir(request)
        template_name = "blog_list_of_posts.html"  # full template
        if request.htmx:
            target_to_template_name = {
                "paging-area": "_list_of_posts_and_paging_controls.html",
            }
            if request.htmx.target is not None:
                template_name = target_to_template_name[request.htmx.target]
            else:
                logger.warning("HTMX target is None")
        template = f"cast/{template_base_dir}/{template_name}"
        return template

    @property
    def last_build_date(self) -> datetime:
        cached = getattr(self, "_last_build_date", None)
        if cached is not None:
            return cached
        newest_post = Post.objects.live().public().descendant_of(self).order_by("-visible_date").first()
        if newest_post is not None:
            return newest_post.visible_date
        if self.first_published_at is not None:
            return self.first_published_at
        return timezone.now()

    @property
    def author_name(self) -> str:
        if self.author is not None:
            return self.author
        return ""

    @property
    def unfiltered_published_posts(self) -> models.QuerySet[Post]:
        return unfiltered_published_posts(self)

    def get_filterset(self, get_params: QueryDict) -> "PostFilterset":
        return create_blog_filterset(self, get_params)

    @staticmethod
    def get_published_posts(filtered_posts: models.QuerySet) -> models.QuerySet[Post]:
        return published_posts_for_index(filtered_posts)

    @staticmethod
    def get_next_and_previous_pages(page: "DjangoPage") -> dict[str, int | None | bool]:
        return next_and_previous_pages(page)

    def get_pagination_context(self, posts_queryset: models.QuerySet["Post"], get_params: QueryDict) -> ContextDict:
        return pagination_context(posts_queryset, get_params)

    @staticmethod
    def get_other_get_params(get_params: QueryDict) -> str:
        return other_get_params(get_params)

    @property
    def wagtail_api_pages_url(self) -> str:
        return reverse("cast:api:wagtail:pages:listing")

    @property
    def facet_counts_api_url(self) -> str:
        return reverse("cast:api:facet-counts-detail", kwargs={"pk": self.pk})

    @property
    def search_suggestions_api_url(self) -> str:
        return reverse("cast:api:search-suggestions-detail", kwargs={"pk": self.pk})

    @property
    def theme_list_api_url(self) -> str:
        return reverse("cast:api:theme-list")

    @property
    def theme_update_api_url(self) -> str:
        return reverse("cast:api:theme-update")

    @property
    def podlove_player_config_url(self) -> str:
        return reverse("cast:api:player_config")

    @property
    def comment_post_url(self) -> str:
        ajax_post_url = reverse("comments-post-comment-ajax")
        return ajax_post_url

    @property
    def pagination_page_size(self) -> int:
        return appsettings.POST_LIST_PAGINATION

    def get_theme_form(self, next_path: str, template_base_dir: str) -> "Form":
        return create_theme_form(next_path, template_base_dir)

    def get_cover_image_context(self) -> dict[str, str]:
        return cover_image_context(self)

    @staticmethod
    def get_context_from_repository(context: ContextDict, repository: BlogIndexContext) -> ContextDict:
        return apply_repository_context(context, repository)

    def get_context(self, request: HtmxHttpRequest, *args: Any, **kwargs: Any) -> ContextDict:
        context = super().get_context(request, *args, **kwargs)
        repository = self.get_repository(request, kwargs)
        return present_blog_index_context(blog=self, request=request, context=context, repository=repository)

    def get_repository(self, request: HtmxHttpRequest, kwargs: dict[str, Any]) -> BlogIndexContext:
        if "repository" in kwargs:
            return kwargs["repository"]
        if appsettings.CAST_REPOSITORY == "default":
            data = BlogIndexContext.data_for_blog_index_cachable(request=request, blog=self)
            return BlogIndexContext.create_from_cachable_data(data=data)
        else:
            # fetch data using Django models as a fall back
            return BlogIndexContext.create_from_django_models(request=request, blog=self)

    def serve(self, request: HtmxHttpRequest, *args: Any, **kwargs: Any) -> TemplateResponse:
        kwargs["repository"] = repository = self.get_repository(request, kwargs)
        kwargs["template_base_dir"] = repository.template_base_dir
        return super().serve(request, *args, **kwargs)


class Podcast(Blog):
    """A podcast is a blog with some extra fields for podcasting."""

    class ItunesType(models.TextChoices):
        EPISODIC = "episodic", _("Episodic")
        SERIAL = "serial", _("Serial")

    # atm it's only used for podcast image
    itunes_artwork: models.ForeignKey = models.ForeignKey(
        ItunesArtWork, null=True, blank=True, on_delete=models.SET_NULL, related_name="podcasts"
    )
    itunes_categories: models.CharField = models.CharField(
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
    keywords: models.CharField = models.CharField(
        _("keywords"),
        max_length=255,
        blank=True,
        default="",
        help_text=_(
            """A comma-delimited list of up to 12 words for iTunes
            searches. Perhaps include misspellings of the title."""
        ),
    )
    EXPLICIT_CHOICES = ((1, _("yes")), (2, _("no")), (3, _("clean")))
    explicit: models.PositiveSmallIntegerField = models.PositiveSmallIntegerField(
        _("explicit"),
        default=1,
        choices=EXPLICIT_CHOICES,
        help_text=_("``Clean`` will put the clean iTunes graphic by it."),
    )
    itunes_type: models.CharField = models.CharField(
        _("iTunes type"),
        max_length=16,
        choices=ItunesType.choices,
        blank=True,
        default="",
        help_text=_("Optional Apple Podcasts channel ordering type. Leave blank to omit the feed tag."),
    )
    automatic_episode_numbering_enabled: models.BooleanField = models.BooleanField(
        default=False,
        help_text=_("Assign the next podcast-scoped number to blank full episodes on their first publish."),
    )
    next_episode_number: models.PositiveIntegerField = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        help_text=_("Next number to try when automatic episode numbering is enabled."),
    )

    content_panels = Page.content_panels + [
        FieldPanel("subtitle", classname="collapsed"),
        FieldPanel("description", classname="full"),
        FieldPanel("email"),
        FieldPanel("author"),
        FieldPanel("comments_enabled"),
        FieldPanel(
            "itunes_artwork", help_text=_("The image that will be used in the podcast feed as the iTunes artwork.")
        ),
        FieldPanel("template_base_dir"),
        MultiFieldPanel(
            [
                FieldPanel("itunes_categories"),
                FieldPanel("keywords"),
                FieldPanel("explicit"),
                FieldPanel("itunes_type"),
                FieldPanel("automatic_episode_numbering_enabled"),
                FieldPanel("next_episode_number"),
            ],
            heading=_("Podcast Settings"),
            classname="collapsed",
        ),
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
    ]

    promote_panels = Page.promote_panels + [
        FieldPanel("noindex"),
    ]

    subpage_types = ["cast.Post", "cast.Episode"]
    is_podcast = True

    objects: PageManager = PageManager()
    aliases_homepage: Any  # don't know why this is needed FIXME

    @property
    def itunes_categories_parsed(self) -> dict[str, list[str]]:
        try:
            return json.loads(self.itunes_categories)
        except json.decoder.JSONDecodeError:
            return {}

    def get_context(self, request: HtmxHttpRequest, *args: Any, **kwargs: Any) -> ContextDict:
        context = super().get_context(request, *args, **kwargs)
        context["podcast"] = self  # convenience
        return context
