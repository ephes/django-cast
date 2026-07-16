from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypedDict, cast

from django.core import validators
from django.core.exceptions import ValidationError

from cast.filters import parse_date_facets
from cast.search_utils import normalize_modelsearch_query

if TYPE_CHECKING:
    from typing import Protocol

    from wagtail.models import Site

    from cast.models import Blog

    class AutocompleteQuerySet(Protocol):
        def autocomplete(
            self,
            query: str,
            *,
            order_by_relevance: bool,
            order_by: str,
        ) -> Any: ...

else:
    AutocompleteQuerySet = object

TYPEAHEAD_MIN_QUERY_LENGTH = 2
TYPEAHEAD_RESULT_LIMIT = 8


class SearchSuggestion(TypedDict):
    id: int
    title: str
    url: str
    visible_date: str


class SearchSuggestionsResponse(TypedDict):
    query: str
    suggestions: list[SearchSuggestion]


def _normalized_slug(value: str) -> str:
    if not value:
        return ""
    try:
        validators.validate_slug(value)
    except ValidationError:
        return ""
    return value


def _apply_facets(queryset: Any, params: Mapping[str, str]) -> Any:
    date_facet = str(params.get("date_facets", ""))
    if date_facet:
        try:
            year_month = parse_date_facets(date_facet)
        except ValueError:
            pass
        else:
            queryset = queryset.filter(
                visible_date__year=year_month.year,
                visible_date__month=year_month.month,
            )

    tag_facet = _normalized_slug(str(params.get("tag_facets", "")))
    if tag_facet:
        queryset = queryset.filter(tags__slug__in=[tag_facet])

    category_facet = _normalized_slug(str(params.get("category_facets", "")))
    if category_facet:
        queryset = queryset.filter(categories__slug__in=[category_facet])

    return queryset


def get_search_suggestions(
    *,
    blog: Blog,
    params: Mapping[str, str],
    current_site: Site | None,
) -> SearchSuggestionsResponse:
    """Return recent title-prefix destinations within a public blog queryset."""
    query = normalize_modelsearch_query(str(params.get("search", "")))
    if len(query) < TYPEAHEAD_MIN_QUERY_LENGTH:
        return {"query": query, "suggestions": []}

    autocomplete_queryset = cast(AutocompleteQuerySet, blog.unfiltered_published_posts)
    search_results = autocomplete_queryset.autocomplete(
        query,
        order_by_relevance=False,
        order_by="-last_published_at",
    )
    queryset = _apply_facets(search_results.get_queryset(), params).order_by("-last_published_at", "-pk")
    posts = list(queryset[:TYPEAHEAD_RESULT_LIMIT])
    return {
        "query": query,
        "suggestions": [
            {
                "id": post.pk,
                "title": post.title,
                "url": post.get_url(current_site=current_site) or "",
                "visible_date": post.visible_date.isoformat(),
            }
            for post in posts
        ],
    }
