"""Internal keyset selection for future paged feeds; existing endpoints do not use it."""

from __future__ import annotations

import binascii
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.core import signing
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.http import Http404, HttpRequest
from django.shortcuts import get_object_or_404
from django.utils import timezone as django_timezone
from wagtail.models import Site

from . import appsettings
from .models.repository import FeedContext, data_for_blog_cachable

if TYPE_CHECKING:
    from .models import Blog, Post

CURSOR_SALT = "cast.feeds.pagination.v1"
MAX_CURSOR_LENGTH = 1024
_ENVELOPE = re.compile(r"[A-Za-z0-9_-]+:[A-Za-z0-9_-]{43}")


class FeedCursorError(Exception):
    """Cursor failures are distinct from service configuration/programming errors."""


class InvalidFeedCursor(FeedCursorError):
    """Malformed or wrong-scope cursor; a future HTTP adapter should return 400."""


class RestartFeedCursor(FeedCursorError):
    """Unverifiable/unsupported cursor; restart at a validated head, never its boundary."""


def _positive_id(value: object) -> bool:
    return type(value) is int and 0 < value <= 2**63 - 1


@dataclass(frozen=True)
class FeedScope:
    site_id: int
    blog_id: int
    kind: str = "blog"
    representation: str = "rss"
    audio_format: str | None = None
    family: str = "paged"

    def __post_init__(self) -> None:
        from .models import Audio

        if not (_positive_id(self.site_id) and _positive_id(self.blog_id)):
            raise ValueError("Feed scope requires positive site and blog IDs")
        if self.kind not in ("blog", "podcast") or self.representation not in ("rss", "atom"):
            raise ValueError("Unsupported feed kind or representation")
        if (self.kind == "blog" and self.audio_format is not None) or (
            self.kind == "podcast" and self.audio_format not in Audio.audio_formats
        ):
            raise ValueError("Invalid audio format for feed kind")
        if not isinstance(self.family, str) or re.fullmatch(r"[a-z][a-z0-9-]{0,31}", self.family) is None:
            raise ValueError("Invalid feed URL family")


@dataclass(frozen=True)
class FeedSelection:
    scope: FeedScope
    ids: tuple[int, ...]
    next_cursor: str | None


def _encode_cursor(scope: FeedScope, date: datetime, pk: int) -> str:
    return signing.Signer(salt=CURSOR_SALT).sign_object(
        {
            "v": 1,
            "order": 1,
            "scope": asdict(scope),
            "date": date.astimezone(timezone.utc).isoformat(timespec="microseconds"),
            "pk": pk,
        }
    )


def decode_cursor(cursor: str, scope: FeedScope) -> tuple[datetime, int]:
    """Verify bounded, uncompressed state before admitting a keyset boundary."""
    if not isinstance(cursor, str) or len(cursor) > MAX_CURSOR_LENGTH or not _ENVELOPE.fullmatch(cursor):
        raise InvalidFeedCursor("Malformed feed cursor")
    try:
        payload = signing.Signer(salt=CURSOR_SALT).unsign_object(cursor)
    except signing.BadSignature as exc:
        raise RestartFeedCursor("Unverifiable feed cursor") from exc
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise InvalidFeedCursor("Invalid feed cursor payload") from exc
    if not isinstance(payload, dict) or type(payload.get("v")) is not int:
        raise InvalidFeedCursor("Invalid feed cursor version")
    if payload["v"] != 1:
        raise RestartFeedCursor("Unsupported feed cursor version")
    if set(payload) != {"v", "order", "scope", "date", "pk"}:
        raise InvalidFeedCursor("Invalid feed cursor fields")
    try:
        decoded_scope = FeedScope(**payload["scope"])
    except (TypeError, ValueError) as exc:
        raise InvalidFeedCursor("Invalid feed cursor scope") from exc
    if payload["scope"] != asdict(scope) or decoded_scope != scope:
        raise InvalidFeedCursor("Feed cursor belongs to another scope")
    if type(payload["order"]) is not int:
        raise InvalidFeedCursor("Invalid feed cursor ordering")
    if payload["order"] != 1:
        raise RestartFeedCursor("Unsupported feed cursor ordering")
    if not _positive_id(payload["pk"]) or not isinstance(payload["date"], str):
        raise InvalidFeedCursor("Invalid feed cursor boundary")
    try:
        date = datetime.fromisoformat(payload["date"])
    except ValueError as exc:
        raise InvalidFeedCursor("Invalid feed cursor date") from exc
    if date.utcoffset() != timedelta(0) or date.isoformat(timespec="microseconds") != payload["date"]:
        raise InvalidFeedCursor("Feed cursor date must be canonical UTC")
    return date, payload["pk"]


class _BeforeBoundary(models.Lookup):
    """Compile resolved columns and prepared values, never interpolated cursor SQL."""

    # Instantiated directly with four operands; deliberately not a registered
    # field lookup (whose constructor protocol would accept only lhs and rhs).
    lookup_name = "feed_before"

    def __init__(self, date: Any, pk: Any, value: Any, key: Any) -> None:
        super().__init__(
            models.Func(date, pk, output_field=models.Field()),
            models.Func(value, key, output_field=models.Field()),
        )

    def as_sql(self, compiler: Any, connection: Any) -> tuple[str, list[Any]]:
        (date, dp), (pk, pp), (value, vp), (key, kp) = (
            compiler.compile(expression)
            for expression in [*self.lhs.get_source_expressions(), *self.rhs.get_source_expressions()]
        )
        if connection.vendor in ("sqlite", "postgresql"):
            return f"({date}, {pk}) < ({value}, {key})", [*dp, *pp, *vp, *kp]
        return f"({date} < {value} OR ({date} = {value} AND {pk} < {key}))", [*dp, *vp, *dp, *vp, *pp, *kp]


def _public_queryset(scope: FeedScope) -> tuple[Blog, models.QuerySet[Post]]:
    from .models import Blog, Podcast, Post

    site = get_object_or_404(Site.objects.select_related("root_page"), pk=scope.site_id)
    root_model = Podcast if scope.kind == "podcast" else Blog
    blog = get_object_or_404(
        root_model.objects.live().public().descendant_of(site.root_page, inclusive=True), pk=scope.blog_id
    )
    queryset = Post.objects.live().public().descendant_of(blog)
    if scope.kind == "podcast":
        queryset = queryset.filter(episode__podcast_audio__isnull=False)
    # Use the Post table's key even for Episode multi-table inheritance, so
    # both tuple columns belong to the composite index. It is also the Page PK.
    return blog, queryset.order_by("-visible_date", "-page_ptr")


def select_feed_page(scope: FeedScope, *, page_size: int = 100, cursor: str | None = None) -> FeedSelection:
    """Select at most N+1 lightweight tuples, without hydrating posts or counting."""
    if type(page_size) is not int or not 1 <= page_size <= 500:
        raise ValueError("Feed page size must be an integer from 1 to 500")
    if not settings.USE_TZ:
        raise ImproperlyConfigured("Feed pagination requires USE_TZ=True for lossless UTC cursors")
    _, queryset = _public_queryset(scope)
    if cursor is not None:
        date, pk = decode_cursor(cursor, scope)
        queryset = queryset.filter(
            _BeforeBoundary(models.F("visible_date"), models.F("page_ptr"), models.Value(date), models.Value(pk))
        )
    rows = list(queryset.values_list("visible_date", "page_ptr")[: page_size + 1])
    selected = rows[:page_size]
    continuation = _encode_cursor(scope, *selected[-1]) if len(rows) > page_size else None
    return FeedSelection(scope, tuple(pk for _, pk in selected), continuation)


def build_feed_page_context(
    request: HttpRequest, selection: FeedSelection, *, repository: str | None = None
) -> FeedContext:
    """Hydrate only selected entries; recheck visibility and never refill a short page."""
    site = Site.find_for_request(request)
    if site is None or site.pk != selection.scope.site_id:
        raise Http404("Feed selection belongs to another site")
    blog, queryset = _public_queryset(selection.scope)
    queryset = queryset.filter(pk__in=selection.ids)
    if selection.scope.kind == "podcast":
        from .models import Episode

        # Select on Post for the compound index, hydrate concrete Episodes for
        # podcast serializers. The subquery retains current public membership.
        queryset = Episode.objects.filter(pk__in=queryset.order_by().values("pk")).order_by("-visible_date", "-pk")
    mode = appsettings.CAST_REPOSITORY if repository is None else repository
    if mode == "default":
        data = data_for_blog_cachable(request=request, blog=blog, post_queryset=queryset, is_paginated=False)
        data["blog_url"] = blog.get_url(request=request)
        context = FeedContext.create_from_cachable_data(data=data)
    elif mode == "django":
        context = FeedContext.create_from_django_models(request=request, blog=blog, post_queryset=queryset)
    else:
        raise ValueError("Unknown feed repository mode")
    if not context.post_by_id:
        # Empty serialized roots have no tree fields; do not fall back to an
        # archive-wide latest-post query when serializing their metadata.
        context.blog._last_build_date = blog.first_published_at or django_timezone.now()
    return context
