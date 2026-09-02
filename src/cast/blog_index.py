from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast

import django.forms.forms
from django.core.paginator import InvalidPage, Page as DjangoPage, Paginator
from django.db import models
from django.http import Http404, QueryDict
from django.utils.translation import gettext_lazy as _

from cast.http_types import HtmxHttpRequest

ContextDict = dict[str, Any]

if TYPE_CHECKING:
    from wagtail.images.models import Image

    from cast.filters import PostFilterset
    from cast.models.index_pages import Blog
    from cast.models.pages import Post
    from cast.models.repository import BlogIndexContext


def unfiltered_published_posts(blog: Blog) -> models.QuerySet[Post]:
    """Return the live public posts below ``blog`` in display order."""
    from cast.models.pages import Post

    if blog.pk is None:
        return Post.objects.none()
    return Post.objects.live().public().descendant_of(blog).order_by("-visible_date")


def create_blog_filterset(blog: Blog, get_params: QueryDict) -> PostFilterset:
    """Build the facet-aware filterset for a blog index request."""
    from cast.filters import PostFilterset

    return PostFilterset(data=get_params, queryset=unfiltered_published_posts(blog))


def create_cached_blog_filterset(filterset_data: Mapping[str, Any]) -> PostFilterset:
    """Rebuild the facet filterset stored at the blog-index cache boundary."""
    from cast.filters import PostFilterset

    filterset = PostFilterset(filterset_data["get_params"])
    filterset.filters["date_facets"].set_field_choices(filterset_data["date_facets_choices"])
    filterset.filters["category_facets"].set_field_choices(filterset_data["category_facets_choices"])
    filterset.filters["tag_facets"].set_field_choices(filterset_data["tag_facets_choices"])
    delattr(filterset, "_form")
    return filterset


def published_posts_for_index(filtered_posts: models.QuerySet[Post]) -> models.QuerySet[Post]:
    """Apply the relations required by blog-index rendering."""
    return filtered_posts.select_related("owner", "cover_image").prefetch_related(
        "audios",
        "images",
        "videos",
        "galleries",
        "galleries__images",
        "images__renditions",
        "galleries__images__renditions",
    )


def next_and_previous_pages(page: DjangoPage) -> dict[str, int | None | bool]:
    """Return stable pagination navigation values for template context."""
    has_previous = page.has_previous()
    has_next = page.has_next()
    return {
        "has_previous": has_previous,
        "previous_page_number": page.previous_page_number() if has_previous else None,
        "has_next": has_next,
        "next_page_number": page.next_page_number() if has_next else None,
    }


def pagination_context(posts_queryset: models.QuerySet[Post], get_params: QueryDict) -> ContextDict:
    """Paginate a blog-index queryset and return its template context."""
    from cast import appsettings

    paginator = Paginator(posts_queryset, appsettings.POST_LIST_PAGINATION)
    page_from_url = str(get_params.get("page", "1"))
    try:
        page_number = int(page_from_url)
    except ValueError:
        if page_from_url == "last":
            page_number = paginator.num_pages
        else:
            raise Http404(_("Page is not “last”, nor can it be converted to an int."))
    try:
        page = paginator.page(page_number)
    except InvalidPage as exc:
        raise Http404(
            _("Invalid page (%(page_number)s): %(message)s") % {"page_number": page_number, "message": str(exc)}
        )
    page_range = page.paginator.get_elided_page_range(page.number, on_each_side=2, on_ends=1)  # type: ignore
    context: ContextDict = {
        "ellipsis": paginator.ELLIPSIS,  # type: ignore
        "page_number": page.number,
        "page_range": list(page_range),
        "object_list": page.object_list,
        "is_paginated": page.has_other_pages(),
    }
    context |= next_and_previous_pages(page)
    return context


def other_get_params(get_params: QueryDict) -> str:
    """Serialize non-pagination query parameters for paging links."""
    filtered_get_params = {key: str(value) for key, value in get_params.items() if key != "page"}
    new_get_params = QueryDict("", mutable=True)
    new_get_params.update(filtered_get_params)
    parameters = new_get_params.urlencode()
    return f"&{parameters}" if parameters else ""


def create_theme_form(next_path: str, template_base_dir: str) -> django.forms.forms.Form:
    """Build the theme selector without coupling the page model to forms."""
    from cast.forms import SelectThemeForm

    return SelectThemeForm(initial={"template_base_dir": template_base_dir, "next": next_path})


def cover_image_context(blog: Blog) -> dict[str, str]:
    """Return the blog cover values consumed by repositories and templates."""
    context = {"cover_image_url": "", "cover_alt_text": ""}
    if blog.cover_image is not None:
        context["cover_image_url"] = cast("Image", blog.cover_image).file.url
        context["cover_alt_text"] = blog.cover_alt_text
    return context


def apply_repository_context(context: ContextDict, repository: BlogIndexContext) -> ContextDict:
    """Add repository-derived blog-index values to Wagtail context."""
    from cast.player import audio_player_context_flags

    context |= repository.pagination_context
    context["filterset"] = repository.filterset
    context["template_base_dir"] = repository.template_base_dir
    context["use_audio_player"] = repository.use_audio_player
    context.update(audio_player_context_flags(enabled=repository.use_audio_player))
    context["root_nav_links"] = repository.root_nav_links
    return context


def present_blog_index_context(
    *,
    blog: Blog,
    request: HtmxHttpRequest,
    context: ContextDict,
    repository: BlogIndexContext,
) -> ContextDict:
    """Assemble the presentation-only portion of a blog-index context."""
    from cast.filters import get_active_facets, has_active_filters
    from cast.follow_links import get_follow_links

    request.cast_site_template_base_dir = repository.template_base_dir
    get_params = request.GET.copy()
    context = apply_repository_context(context, repository)
    context["repository"] = repository
    context["posts"] = context["object_list"]
    context["blog"] = blog
    context["canonical_url"] = blog.full_url
    context["has_selectable_themes"] = True
    context["parameters"] = other_get_params(get_params)
    context["theme_form"] = create_theme_form(request.path, context["template_base_dir"])
    context["template_base_dir_choices"] = context["theme_form"].fields["template_base_dir"].choices
    context["next_url"] = request.get_full_path()
    context["follow_links"] = get_follow_links(blog)
    context["active_facets"] = get_active_facets(context["filterset"], request)
    context["has_active_filters"] = has_active_filters(context["filterset"], request)
    return context
