import json
import logging
import uuid
from datetime import datetime
from typing import Any

import django.forms.forms
from django.core.paginator import InvalidPage
from django.core.paginator import Page as DjangoPage
from django.core.paginator import Paginator
from django.db import models
from django.http import Http404
from django.http.request import QueryDict
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from wagtail.admin.panels import FieldPanel
from wagtail.api import APIField
from wagtail.fields import RichTextField
from wagtail.models import Page, PageManager

from cast import appsettings
from cast.filters import PostFilterset
from cast.models.itunes import ItunesArtWork

from ..views import HtmxHttpRequest
from .pages import Post
from .repository import BlogIndexRepository
from .theme import get_template_base_dir, get_template_base_dir_choices

logger = logging.getLogger(__name__)


ContextDict = dict[str, Any]


class Blog(Page):
    """
    This is the index page for a blog. It contains a list of posts.
    """

    author = models.CharField(
        max_length=255,
        default=None,
        null=True,
        blank=True,
        help_text=_("Freeform text that will be used in the feed."),
    )
    uuid = models.UUIDField(default=uuid.uuid4, editable=False)
    email = models.EmailField(null=True, default=None, blank=True)
    comments_enabled = models.BooleanField(
        _("comments_enabled"),
        default=True,
        help_text=_("Whether comments are enabled for this blog." ""),
    )
    noindex = models.BooleanField(
        "noindex",
        default=False,
        help_text=_(
            "Whether to add a noindex meta tag to this page and all subpages excluding them from search engines."
        ),
    )
    template_base_dir = models.CharField(
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
    description = RichTextField(blank=True)
    content_panels = Page.content_panels + [
        FieldPanel("description", classname="full"),
        FieldPanel("email"),
        FieldPanel("author"),
        FieldPanel("template_base_dir"),
    ]
    promote_panels = Page.promote_panels + [
        FieldPanel("noindex"),
    ]
    api_fields = [
        APIField("description"),
    ]

    subpage_types = ["cast.Post"]
    is_podcast = False

    def __str__(self):
        return self.title

    def get_template_base_dir(self, request: HtmxHttpRequest) -> str:
        return get_template_base_dir(request, self.template_base_dir)

    def get_template(self, request: HtmxHttpRequest, *args, **kwargs) -> str:
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
        return Post.objects.live().descendant_of(self.blog).order_by("-visible_date")[0].visible_date

    @property
    def author_name(self) -> str:
        if self.author is not None:
            return self.author
        else:
            return self.owner.get_full_name()

    @property
    def unfiltered_published_posts(self) -> models.QuerySet[Post]:
        if self.pk is None:
            # this blog is not saved to database yet, therefore it has no posts
            return Post.objects.none()
        return Post.objects.live().descendant_of(self).order_by("-visible_date")

    def get_filterset(self, get_params: QueryDict) -> PostFilterset:
        return PostFilterset(data=get_params, queryset=self.unfiltered_published_posts)

    @staticmethod
    def get_published_posts(filtered_posts: models.QuerySet) -> models.QuerySet[Post]:
        queryset = filtered_posts
        queryset = queryset.select_related("owner")
        queryset = queryset.prefetch_related(
            "audios",
            "images",
            "videos",
            "galleries",
            "galleries__images",
            "images__renditions",
            "galleries__images__renditions",
        )
        return queryset

    @staticmethod
    def get_next_and_previous_pages(page: DjangoPage) -> dict[str, int | None | bool]:
        previous_page_number = None
        has_previous = page.has_previous()
        if has_previous:
            previous_page_number = page.previous_page_number()
        has_next = page.has_next()
        next_page_number = None
        if has_next:
            next_page_number = page.next_page_number()
        return {
            "has_previous": has_previous,
            "previous_page_number": previous_page_number,
            "has_next": has_next,
            "next_page_number": next_page_number,
        }

    def get_pagination_context(self, posts_queryset: models.QuerySet["Post"], get_params: QueryDict) -> ContextDict:
        paginator = Paginator(posts_queryset, appsettings.POST_LIST_PAGINATION)
        page_from_url = "1"
        if "page" in get_params:
            page_from_url = str(get_params["page"])
        try:
            page_number = int(page_from_url)
        except ValueError:
            if page_from_url == "last":
                page_number = paginator.num_pages
            else:
                raise Http404(_("Page is not “last”, nor can it be converted to an int."))
        try:
            page = paginator.page(page_number)
        except InvalidPage as e:
            raise Http404(
                _("Invalid page (%(page_number)s): %(message)s") % {"page_number": page_number, "message": str(e)}
            )
        page_range = page.paginator.get_elided_page_range(page.number, on_each_side=2, on_ends=1)  # type: ignore
        pagination_context = {
            "ellipsis": paginator.ELLIPSIS,  # type: ignore
            "page_number": page.number,
            "page_range": list(page_range),
            "object_list": page.object_list,
            "is_paginated": page.has_other_pages(),
        }
        pagination_context |= self.get_next_and_previous_pages(page)
        return pagination_context

    @staticmethod
    def get_other_get_params(get_params: QueryDict) -> str:
        filtered_get_params = {k: str(v) for k, v in get_params.items() if k != "page"}
        new_get_params = QueryDict("", mutable=True)
        new_get_params.update(filtered_get_params)
        parameters = new_get_params.urlencode()
        if len(parameters) > 0:
            parameters = f"&{parameters}"
        return parameters

    @property
    def wagtail_api_pages_url(self) -> str:
        return reverse("cast:api:wagtail:pages:listing")

    @property
    def facet_counts_api_url(self) -> str:
        return reverse("cast:api:facet-counts-detail", kwargs={"pk": self.pk})

    @property
    def theme_list_api_url(self) -> str:
        return reverse("cast:api:theme-list")

    @property
    def theme_update_api_url(self) -> str:
        return reverse("cast:api:theme-update")

    @property
    def comment_post_url(self) -> str:
        ajax_post_url = reverse("comments-post-comment-ajax")
        return ajax_post_url

    @property
    def pagination_page_size(self) -> int:
        return appsettings.POST_LIST_PAGINATION

    def get_theme_form(self, next_path: str, template_base_dir: str) -> django.forms.forms.Form:
        from ..forms import SelectThemeForm

        return SelectThemeForm(
            initial={
                "template_base_dir": template_base_dir,
                "next": next_path,
            }
        )

    @staticmethod
    def get_context_from_repository(context: ContextDict, repository: BlogIndexRepository) -> ContextDict:
        context |= repository.pagination_context  # includes object_list
        context["filterset"] = repository.filterset
        context["template_base_dir"] = repository.template_base_dir
        context["use_audio_player"] = repository.use_audio_player
        context["root_nav_links"] = repository.root_nav_links
        return context

    def get_context(self, request: HtmxHttpRequest, *args, **kwargs) -> ContextDict:
        context = super().get_context(request, *args, **kwargs)
        context["repository"] = repository = self.get_repository(request, kwargs)
        get_params = request.GET.copy()
        context = self.get_context_from_repository(context, repository)
        context["posts"] = context["object_list"]  # convenience
        context["blog"] = self
        context["has_selectable_themes"] = True
        context["parameters"] = self.get_other_get_params(get_params)
        context["theme_form"] = self.get_theme_form(request.path, context["template_base_dir"])
        return context

    def get_repository(self, request: HtmxHttpRequest, kwargs: dict[str, Any]) -> BlogIndexRepository:
        if "repository" in kwargs:
            return kwargs["repository"]
        if appsettings.CAST_REPOSITORY == "default":
            data = BlogIndexRepository.data_for_blog_index_cachable(request=request, blog=self)
            return BlogIndexRepository.create_from_cachable_data(data=data)
        else:
            # fetch data using Django models as a fall back
            return BlogIndexRepository.create_from_django_models(request=request, blog=self)

    def serve(self, request: HtmxHttpRequest, *args, **kwargs) -> TemplateResponse:
        kwargs["repository"] = repository = self.get_repository(request, kwargs)
        kwargs["template_base_dir"] = repository.template_base_dir
        return super().serve(request, *args, **kwargs)


class Podcast(Blog):
    """A podcast is a blog with some extra fields for podcasting."""

    # atm it's only used for podcast image
    itunes_artwork = models.ForeignKey(
        ItunesArtWork, null=True, blank=True, on_delete=models.SET_NULL, related_name="podcasts"
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
    keywords = models.CharField(
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
    explicit = models.PositiveSmallIntegerField(
        _("explicit"),
        default=1,
        choices=EXPLICIT_CHOICES,
        help_text=_("``Clean`` will put the clean iTunes graphic by it."),
    )

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
