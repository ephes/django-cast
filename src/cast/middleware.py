"""Middleware for django-cast."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from django.http import HttpRequest
from django.http.response import HttpResponseBase
from django.middleware.cache import FetchFromCacheMiddleware, UpdateCacheMiddleware
from django.utils.module_loading import import_string

MIDDLEWARE_PATH = "cast.middleware.PagedFeedCacheMiddleware"
FULL_SITE_CACHE_MIDDLEWARE = (UpdateCacheMiddleware, FetchFromCacheMiddleware)


class PagedFeedCacheMiddleware:
    """Outermost response hook for paged feed routes; transparent for every other request.

    Must be the first MIDDLEWARE entry when ``CAST_FEED_PAGINATION`` is
    configured, so its response hook sees the final headers after session,
    CSRF, locale, conditional-GET and compression middleware. It evaluates the
    paged routes' preconditions and removes HEAD bodies only then.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponseBase]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponseBase:
        from .paged_feeds import REQUEST_STATE_ATTRIBUTE, PagedFeedRequestState, finalize_paged_feed_response

        state = PagedFeedRequestState()
        setattr(request, REQUEST_STATE_ATTRIBUTE, state)
        response = self.get_response(request)
        if not state.paged:
            return response
        return finalize_paged_feed_response(request, state, response)


def _middleware_class(path: object) -> type | None:
    try:
        imported = import_string(str(path))
    except ImportError:
        return None
    return imported if isinstance(imported, type) else None


def paged_feed_middleware_errors(middleware: Sequence[object]) -> list[tuple[str, str]]:
    """Pure placement checks as ``(check id, message)`` pairs; imports classes, never queries."""
    classes = [(str(path), _middleware_class(path)) for path in middleware]
    guards = [index for index, (_, cls) in enumerate(classes) if cls and issubclass(cls, PagedFeedCacheMiddleware)]
    errors: list[tuple[str, str]] = []
    if guards != [0]:
        errors.append(
            (
                "cast.E015",
                f"CAST_FEED_PAGINATION requires {MIDDLEWARE_PATH} exactly once, as the first MIDDLEWARE entry.",
            )
        )
    for path, cls in classes:
        if cls and issubclass(cls, FULL_SITE_CACHE_MIDDLEWARE):
            errors.append(
                ("cast.E016", f"CAST_FEED_PAGINATION is incompatible with Django full-site cache middleware {path}.")
            )
    return errors
