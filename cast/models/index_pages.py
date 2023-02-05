import json
import logging
import uuid
from typing import Optional, Union

from django.core.paginator import InvalidPage, Paginator
from django.db import models
from django.http import Http404, HttpRequest
from django.http.request import QueryDict
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from wagtail.admin.edit_handlers import FieldPanel
from wagtail.core.fields import RichTextField
from wagtail.core.models import Page

from cast import appsettings
from cast.filters import PostFilterset
from cast.models.itunes import ItunesArtWork

from .pages import Post

logger = logging.getLogger(__name__)


class Blog(Page):
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

    # wagtail
    description = RichTextField(blank=True)
    template = "cast/blog_list_of_posts.html"
    content_panels = Page.content_panels + [
        FieldPanel("description", classname="full"),
        FieldPanel("email"),
        FieldPanel("author"),
    ]

    subpage_types = ["cast.Post"]
    is_podcast = False

    def __str__(self):
        return self.title

    @property
    def last_build_date(self) -> timezone.datetime:
        return Post.objects.live().descendant_of(self.blog).order_by("-visible_date")[0].visible_date

    @property
    def author_name(self) -> str:
        if self.author is not None:
            return self.author
        else:
            return self.owner.get_full_name()

    @property
    def unfiltered_published_posts(self) -> models.QuerySet[Post]:
        return Post.objects.live().descendant_of(self).order_by("-visible_date")

    @property
    def request(self) -> Optional[HttpRequest]:
        return getattr(self, "_request", None)

    @request.setter
    def request(self, value: HttpRequest) -> None:
        self._request = value

    @property
    def filterset_data(self) -> Union[QueryDict, dict]:
        if self.request is not None:
            return self.request.GET
        else:
            return getattr(self, "_filterset_data", {})

    @property
    def filterset(self):
        return PostFilterset(
            data=self.filterset_data, queryset=self.unfiltered_published_posts, fetch_facet_counts=True
        )

    @property
    def published_posts(self):
        return self.filterset.qs

    def paginate_queryset(self, context):
        paginator = Paginator(self.published_posts, appsettings.POST_LIST_PAGINATION)
        page = self.request.GET.get("page", False) or 1
        try:
            page_number = int(page)
        except ValueError:
            if page == "last":
                page_number = paginator.num_pages
            else:
                raise Http404(_("Page is not “last”, nor can it be converted to an int."))
        try:
            page = paginator.page(page_number)
        except InvalidPage as e:
            raise Http404(
                _("Invalid page (%(page_number)s): %(message)s") % {"page_number": page_number, "message": str(e)}
            )
        pagination_context = {
            "paginator": paginator,
            "page_obj": page,
            "is_paginated": page.has_other_pages(),
            "object_list": page.object_list,
        }
        context.update(pagination_context)
        return context

    def get_other_get_params(self):
        get_copy = self.request.GET.copy()
        parameters = get_copy.pop("page", True) and get_copy.urlencode()
        if len(parameters) > 0:
            parameters = f"&{parameters}"
        return parameters

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        self.request = request
        context["filterset"] = self.filterset
        context["parameters"] = self.get_other_get_params()
        context = self.paginate_queryset(context)
        context["posts"] = context["object_list"]  # convenience
        return context


class Podcast(Blog):
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

    template = "cast/blog_list_of_posts.html"
    subpage_types = ["cast.Post", "cast.Episode"]
    is_podcast = True

    @property
    def itunes_categories_parsed(self) -> dict[str, list[str]]:
        try:
            return json.loads(self.itunes_categories)
        except json.decoder.JSONDecodeError:
            return {}
