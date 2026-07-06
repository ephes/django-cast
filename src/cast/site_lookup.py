from __future__ import annotations

from typing import Any, TypeVar, cast

from django.db.models import Model, QuerySet
from django.http import Http404, HttpRequest
from django.shortcuts import get_object_or_404
from wagtail.models import Site

ModelT = TypeVar("ModelT", bound=Model)


def site_specific_queryset(model: type[ModelT], request: HttpRequest, *, live: bool = True) -> QuerySet[ModelT]:
    """Return a site-scoped queryset for Wagtail page models.

    Non-page querysets are tolerated and simply skip the Wagtail-specific
    `live()` / `descendant_of()` narrowing when those methods are absent.
    """
    queryset = cast(QuerySet[ModelT], cast(Any, model).objects.all())
    if live and hasattr(queryset, "live"):
        queryset = cast(QuerySet[ModelT], queryset.live())
    site = Site.find_for_request(request)
    if site is not None and site.root_page_id is not None and hasattr(queryset, "descendant_of"):
        queryset = cast(QuerySet[ModelT], queryset.descendant_of(site.root_page))
    return queryset


def get_site_specific_page_or_404(
    model: type[ModelT], request: HttpRequest, *, slug: str, live: bool = True
) -> ModelT:
    queryset = site_specific_queryset(model, request, live=live)
    multiple_objects_returned = cast(Any, model).MultipleObjectsReturned
    try:
        return cast(ModelT, get_object_or_404(queryset, slug=slug))
    except multiple_objects_returned as exc:
        raise Http404(f"Multiple {model.__name__} pages found for slug {slug!r} on this site.") from exc
