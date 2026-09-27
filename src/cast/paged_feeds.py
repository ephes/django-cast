"""Admission, serialization, response caching and HTTP policy for paged feeds.

The public routes in ``cast.urls`` use :func:`paged_feed_view`. It admits a
configured request, validates its bounded query and cursor signature, looks up
a 300-second serialized representation and otherwise selects one keyset page
and serializes it through request-local subclasses of the existing feed
classes. It always returns the complete GET representation as a ``no-store``
candidate without validators. ``cast.middleware.PagedFeedCacheMiddleware``
finalizes every paged response after all other middleware: it evaluates
preconditions (304/412), applies the shared-cache policy, strips HEAD bodies
and performs deferred cache insertion.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, cast
from urllib.parse import unquote_plus, urlencode

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.http import (
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseBase,
    HttpResponseNotAllowed,
    HttpResponseNotFound,
    HttpResponseRedirect,
    QueryDict,
    StreamingHttpResponse,
)
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.cache import get_conditional_response
from django.utils.crypto import salted_hmac
from django.utils.feedgenerator import Rss201rev2Feed
from django.utils.xmlutils import SimplerXMLGenerator
from django_htmx.middleware import HtmxDetails
from wagtail.models import Site

from . import appsettings
from .feed_pagination import FeedOwner, feed_pagination_records, request_host_and_port, resolve_request_owner
from .feed_selection import (
    CURSOR_SALT,
    FeedScope,
    FeedSelection,
    InvalidFeedCursor,
    RestartFeedCursor,
    build_feed_page_context,
    decode_cursor,
    select_feed_page,
)
from .feeds import (
    AtomFeedWithStylesheets,
    AtomITunesFeedGenerator,
    AtomPodcastFeed,
    LatestEntriesAtomFeed,
    LatestEntriesFeed,
    PodcastFeed,
    RepositoryMixin,
    RssITunesFeedGenerator,
    RssPodcastFeed,
)
from .http_types import HtmxHttpRequest
from .middleware import MIDDLEWARE_PATH, paged_feed_middleware_errors
from .models import Blog, Podcast
from .models.repository import FeedContext

MAX_QUERY_BYTES = 4096
URL_NAMESPACE = "cast"
PAGED_FEED_URL_NAMES: dict[tuple[str, str], str] = {
    ("blog", "rss"): "paged_entries_feed",
    ("blog", "atom"): "paged_entries_atom_feed",
    ("podcast", "rss"): "paged_podcast_feed_rss",
    ("podcast", "atom"): "paged_podcast_feed_atom",
}
_MALFORMED_PERCENT = re.compile(r"%(?![0-9A-Fa-f]{2})")
_DEFAULT_PORTS = {"http": 80, "https": 443}
# Policy of the isolated, uncached internal test adapter and of every public non-200 outcome.
INTERNAL_CACHE_CONTROL = "no-store"
ERROR_CACHE_CONTROL = "no-store"
# The view's candidate stays no-store until the final hook promotes it, so inner
# middleware (e.g. ConditionalGetMiddleware) neither adds validators nor answers 304.
CANDIDATE_CACHE_CONTROL = "no-store"
CACHE_SECONDS = 300
PUBLIC_CACHE_CONTROL = f"public, max-age={CACHE_SECONDS}"
UNSAFE_CACHE_CONTROL = "private, no-store"
# Bump when serialized semantics or the stored layout change across deployments.
CACHE_NAMESPACE = "cast.paged-feeds.v1"
PERMITTED_VARY = frozenset({"accept-encoding", "accept-language"})
REQUEST_STATE_ATTRIBUTE = "_cast_paged_feed_state"
_VALIDATOR_HEADERS = ("ETag", "Last-Modified", "Age", "Expires")


class InvalidPagedFeedQuery(InvalidFeedCursor):
    """The raw query is not empty or exactly one well-formed nonempty ``cursor``."""


def parse_paged_feed_query(query_string: str) -> str | None:
    """Return the decoded cursor, None for the head, or raise InvalidPagedFeedQuery.

    The raw query is bounded before parsing. Accepted queries are ASCII, so the
    character bound equals the byte bound; percent escapes must be complete and
    decode to strict UTF-8.
    """
    if len(query_string) > MAX_QUERY_BYTES:
        raise InvalidPagedFeedQuery("Feed query is too long")
    if query_string == "":
        return None
    if not query_string.isascii() or _MALFORMED_PERCENT.search(query_string):
        raise InvalidPagedFeedQuery("Malformed feed query encoding")
    if "&" in query_string:
        raise InvalidPagedFeedQuery("Feed query accepts exactly one parameter")
    raw_key, separator, raw_value = query_string.partition("=")
    try:
        key = unquote_plus(raw_key, errors="strict")
        value = unquote_plus(raw_value, errors="strict")
    except UnicodeDecodeError as exc:
        raise InvalidPagedFeedQuery("Malformed feed query encoding") from exc
    if not separator or key != "cursor" or value == "":
        raise InvalidPagedFeedQuery("Feed query accepts only one nonempty cursor")
    return value


@dataclass(frozen=True)
class PagedFeedTarget:
    """An admitted paged feed request: owner, cursor scope and canonical document URLs."""

    owner: FeedOwner
    scope: FeedScope
    cursor: str | None
    scheme: str
    hostname: str
    port: int
    head_path: str
    path_info: str

    @property
    def host(self) -> str:
        """Normalized host, with the port only when it is not the scheme default."""
        if _DEFAULT_PORTS.get(self.scheme) == self.port:
            return self.hostname
        return f"{self.hostname}:{self.port}"

    @property
    def head_url(self) -> str:
        return f"{self.scheme}://{self.host}{self.head_path}"

    @property
    def query_string(self) -> str:
        return "" if self.cursor is None else urlencode({"cursor": self.cursor})

    def page_url(self, cursor: str | None) -> str:
        """Rebuild a page URL from a decoded cursor with standard query encoding."""
        if cursor is None:
            return self.head_url
        return f"{self.head_url}?{urlencode({'cursor': cursor})}"

    @property
    def document_url(self) -> str:
        return self.page_url(self.cursor)


def reverse_paged_feed_path(request: HttpRequest, scope: FeedScope, slug: str) -> str:
    """Reverse the paged route, keeping script, mount and URL-language prefixes.

    The language prefix comes from the request path, not from negotiated or
    fixed rendering languages, so the canonical URL is the one requested.
    """
    kwargs = {"slug": slug}
    if scope.audio_format is not None:
        kwargs["audio_format"] = scope.audio_format
    name = f"{URL_NAMESPACE}:{PAGED_FEED_URL_NAMES[(scope.kind, scope.representation)]}"
    url_language = translation.get_language_from_path(request.path_info) or settings.LANGUAGE_CODE
    with translation.override(url_language):
        return reverse(name, kwargs=kwargs, urlconf=getattr(request, "urlconf", None))


def admit_paged_feed_request(
    request: HttpRequest,
    *,
    slug: str,
    kind: str,
    representation: str,
    audio_format: str | None = None,
) -> PagedFeedTarget:
    """Resolve the configured owner (404), then admit the query (InvalidPagedFeedQuery).

    The requested path must equal the reversed paged route, so the canonical
    self URL cannot come from an unexpected alias.
    """
    owner = resolve_request_owner(request, slug=slug, kind=kind, audio_format=audio_format)
    scope = FeedScope(
        owner.site.pk, owner.blog.pk, kind=kind, representation=representation, audio_format=audio_format
    )
    head_path = reverse_paged_feed_path(request, scope, owner.blog.slug)
    if request.path != head_path:
        raise Http404("Request path is not the canonical paged feed route")
    cursor = parse_paged_feed_query(request.META.get("QUERY_STRING", ""))
    hostname, port = request_host_and_port(request)
    return PagedFeedTarget(
        owner, scope, cursor, request.scheme or "http", hostname, port, head_path, request.path_info
    )


def select_paged_feed(target: PagedFeedTarget) -> FeedSelection:
    """Select one page with the configured size; raises the decoder's cursor errors unchanged."""
    return select_feed_page(target.scope, page_size=target.owner.record.page_size, cursor=target.cursor)


class IsolatedFeedRequest(HttpRequest):
    """Anonymous public GET request carrying only a validated origin, path and Site.

    Cookies, session, user, HTMX headers, forwarding headers and theme overrides
    of the caller are never copied, so they cannot influence shared XML.
    """

    def __init__(self, target: PagedFeedTarget) -> None:
        super().__init__()
        self._fixed_scheme = target.scheme
        self.method = "GET"
        self.path = target.head_path
        self.path_info = target.path_info
        self.META = {
            "REQUEST_METHOD": "GET",
            "HTTP_HOST": target.host,
            "SERVER_NAME": target.hostname,
            "SERVER_PORT": str(target.port),
            "QUERY_STRING": target.query_string,
        }
        self.GET = QueryDict(target.query_string)
        self.user = AnonymousUser()
        self.htmx = HtmxDetails(self)
        self.LANGUAGE_CODE = settings.LANGUAGE_CODE
        self._wagtail_site: Site = target.owner.site

    def _get_scheme(self) -> str:
        return self._fixed_scheme


@dataclass(frozen=True)
class PagedFeedNavigation:
    """Request-local navigation links; ``self`` is emitted by the generator from ``feed_url``."""

    self_url: str
    first_url: str
    next_url: str | None
    mime_type: str

    def links(self) -> list[tuple[str, str]]:
        links = [("first", self.first_url)]
        if self.next_url is not None:
            links.append(("next", self.next_url))
        return links


class _PagedNavigationGeneratorMixin:
    """Append RFC 5005 first/next Atom links after all existing root elements."""

    feed: dict[str, Any]
    navigation_element = "link"

    def add_root_elements(self, handler: SimplerXMLGenerator) -> None:
        super().add_root_elements(handler)  # type: ignore[misc]
        navigation: PagedFeedNavigation = self.feed["paged_navigation"]
        for rel, href in navigation.links():
            handler.addQuickElement(
                self.navigation_element, None, {"rel": rel, "href": href, "type": navigation.mime_type}
            )


class PagedRssFeedGenerator(_PagedNavigationGeneratorMixin, Rss201rev2Feed):
    navigation_element = "atom:link"


class PagedAtomFeedGenerator(_PagedNavigationGeneratorMixin, AtomFeedWithStylesheets):
    pass


class PagedRssITunesFeedGenerator(_PagedNavigationGeneratorMixin, RssITunesFeedGenerator):
    navigation_element = "atom:link"


class PagedAtomITunesFeedGenerator(_PagedNavigationGeneratorMixin, AtomITunesFeedGenerator):
    pass


class _PagedFeedMixin(RepositoryMixin):
    """Serialize exactly one injected bounded context; never build a full-archive repository."""

    navigation: PagedFeedNavigation

    def __init__(self, repository: FeedContext, navigation: PagedFeedNavigation) -> None:
        super().__init__(repository=repository)
        self.navigation = navigation

    def get_repository(self, request: HtmxHttpRequest, blog: Blog) -> FeedContext:
        return self._bounded_repository()

    def _bounded_repository(self) -> FeedContext:
        if self.repository is None or self.repository.used:
            raise RuntimeError("Paged feeds serialize one bounded context exactly once")
        return self.repository

    def _bounded_blog(self, request: HttpRequest) -> Blog:
        blog = self._bounded_repository().blog
        self.request = cast(HtmxHttpRequest, request)
        return blog

    def feed_url(self, _obj: Blog) -> str:
        return self.navigation.self_url

    def feed_extra_kwargs(self, obj: Any) -> dict[str, Any]:
        return {**super().feed_extra_kwargs(obj), "paged_navigation": self.navigation}


class _PagedBlogFeedMixin(_PagedFeedMixin):
    object: Blog

    def get_object(self, request: HttpRequest, *args: Any, **kwargs: Any) -> Blog:
        self.object = self._bounded_blog(request)
        return self.object


class _PagedPodcastFeedMixin(_PagedFeedMixin):
    object: Podcast

    def get_object(self, request: HttpRequest, *args: Any, **kwargs: Any) -> Podcast:
        cast(PodcastFeed, self).set_audio_format(kwargs["audio_format"])
        blog = self._bounded_blog(request)
        if not isinstance(blog, Podcast):
            raise Http404("Paged podcast feeds require a Podcast")
        self.object = blog
        return self.object


class PagedEntriesFeed(_PagedBlogFeedMixin, LatestEntriesFeed):
    feed_type = PagedRssFeedGenerator


class PagedEntriesAtomFeed(_PagedBlogFeedMixin, LatestEntriesAtomFeed):
    feed_type = PagedAtomFeedGenerator


class PagedRssPodcastFeed(_PagedPodcastFeedMixin, RssPodcastFeed):
    feed_type = PagedRssITunesFeedGenerator


class PagedAtomPodcastFeed(_PagedPodcastFeedMixin, AtomPodcastFeed):
    feed_type = PagedAtomITunesFeedGenerator


PAGED_FEED_CLASSES: dict[tuple[str, str], type[_PagedFeedMixin]] = {
    ("blog", "rss"): PagedEntriesFeed,
    ("blog", "atom"): PagedEntriesAtomFeed,
    ("podcast", "rss"): PagedRssPodcastFeed,
    ("podcast", "atom"): PagedAtomPodcastFeed,
}


@dataclass(frozen=True)
class RenderedPagedFeed:
    """Serialized bytes and representation metadata, with no request or repository state."""

    content: bytes
    content_type: str
    document_url: str
    next_url: str | None


def render_paged_feed(
    target: PagedFeedTarget, selection: FeedSelection, *, repository: str | None = None
) -> RenderedPagedFeed:
    """Hydrate and serialize the selected page in an isolated, fixed-locale public request.

    Rendering uses settings.LANGUAGE_CODE and settings.TIME_ZONE through scoped
    overrides; the caller's request, active language and timezone are unchanged.
    """
    if selection.scope != target.scope:
        raise ValueError("Feed selection does not belong to the admitted target")
    feed_class = PAGED_FEED_CLASSES[(target.scope.kind, target.scope.representation)]
    content_type = cast(type[Rss201rev2Feed], feed_class.feed_type).content_type
    next_url = None if selection.next_cursor is None else target.page_url(selection.next_cursor)
    navigation = PagedFeedNavigation(
        self_url=target.document_url,
        first_url=target.head_url,
        next_url=next_url,
        mime_type=content_type.split(";", 1)[0],
    )
    request = IsolatedFeedRequest(target)
    kwargs = {"slug": target.owner.blog.slug}
    if target.scope.audio_format is not None:
        kwargs["audio_format"] = target.scope.audio_format
    with translation.override(settings.LANGUAGE_CODE), timezone.override(settings.TIME_ZONE):
        context = build_feed_page_context(request, selection, repository=repository)
        feed = feed_class(repository=context, navigation=navigation)
        generator = feed.get_feed(cast(Blog, feed.get_object(request, **kwargs)), request)
        # Serialize like Feed.__call__, without its newest-item Last-Modified header.
        output = HttpResponse(content_type=content_type)
        generator.write(output, "utf-8")
    return RenderedPagedFeed(output.content, content_type, target.document_url, next_url)


def _internal_policy(response: HttpResponse) -> HttpResponse:
    response["Cache-Control"] = INTERNAL_CACHE_CONTROL
    return response


def internal_paged_feed_response(
    request: HttpRequest,
    *,
    slug: str,
    kind: str,
    representation: str,
    audio_format: str | None = None,
) -> HttpResponse:
    """Internal, uncached HTTP adapter for integration tests; not the public cache policy.

    Returns 405 for other methods, 404 for unavailable owners, a generic 400 for
    malformed input or verified wrong scope, a 302 to the validated head for
    unverifiable or unsupported cursors, and otherwise the serialized page.
    """
    if request.method not in ("GET", "HEAD"):
        return _internal_policy(HttpResponseNotAllowed(["GET", "HEAD"]))
    try:
        target = admit_paged_feed_request(
            request, slug=slug, kind=kind, representation=representation, audio_format=audio_format
        )
        selection = select_paged_feed(target)
    except InvalidFeedCursor:
        return _internal_policy(HttpResponseBadRequest(b"Invalid feed request", content_type="text/plain"))
    except RestartFeedCursor:
        return _internal_policy(HttpResponseRedirect(target.head_url))
    rendered = render_paged_feed(target, selection)
    response = HttpResponse(b"" if request.method == "HEAD" else rendered.content, content_type=rendered.content_type)
    return _internal_policy(response)


# Public routes: bounded response cache and final HTTP policy


def _now() -> float:
    return time.time()


@dataclass(frozen=True)
class CachedPagedFeed:
    """An immutable full 200 representation: bytes, content type, weak ETag and generation time."""

    content: bytes
    content_type: str
    etag: str
    generated_at: float

    def as_cache_value(self) -> tuple[str, bytes, str, str, float]:
        return (CACHE_NAMESPACE, self.content, self.content_type, self.etag, self.generated_at)

    @classmethod
    def from_cache_value(cls, value: object) -> CachedPagedFeed | None:
        """Return the stored representation, or None for a miss or an unrecognized layout."""
        if not (isinstance(value, tuple) and len(value) == 5 and value[0] == CACHE_NAMESPACE):
            return None
        _, content, content_type, etag, generated_at = value
        if not (
            isinstance(content, bytes)
            and isinstance(content_type, str)
            and isinstance(etag, str)
            and type(generated_at) is float
        ):
            return None
        return cls(content, content_type, etag, generated_at)

    def age(self) -> int:
        """Seconds since generation, not since this hit."""
        return max(0, int(_now() - self.generated_at))


@dataclass
class PagedFeedRequestState:
    """Private per-request metadata shared by the paged view and the outermost middleware.

    ``entry`` and ``candidate`` (the view's own full 200 response) are set only
    for a successful representation; ``hit`` tells the final hook whether it
    came from the cache (never reinserted) or awaits insertion.
    """

    paged: bool = False
    cache_key: str | None = None
    entry: CachedPagedFeed | None = None
    candidate: HttpResponse | None = None
    hit: bool = False


def signing_key_digest() -> str:
    """One-way digest of the active cursor signing key; the key itself is never exposed."""
    return salted_hmac("cast.paged-feeds.cache.signing-key", CURSOR_SALT, algorithm="sha256").hexdigest()


def paged_feed_cache_key(target: PagedFeedTarget) -> str:
    """Versioned key over every input that can change the serialized representation."""
    record = target.owner.record
    identity = {
        "document_url": target.document_url,
        "site": target.owner.site.pk,
        "blog": target.owner.blog.pk,
        "scope": asdict(target.scope),
        "policy": [record.hostname, record.port, record.blog_path, record.page_size],
        "repository": appsettings.CAST_REPOSITORY,
        "language": settings.LANGUAGE_CODE,
        "time_zone": settings.TIME_ZONE,
        "signing_key": signing_key_digest(),
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return f"{CACHE_NAMESPACE}:{digest}"


def paged_feed_etag(content: bytes, document_url: str) -> str:
    """Weak ETag over the serialized bytes, canonical document URL and fixed locale settings."""
    digest = hashlib.sha256()
    for part in (content, document_url.encode(), settings.LANGUAGE_CODE.encode(), settings.TIME_ZONE.encode()):
        digest.update(len(part).to_bytes(8, "big"))
        digest.update(part)
    return f'W/"{digest.hexdigest()}"'


def _cached_entry(key: str) -> CachedPagedFeed | None:
    """Return a fresh stored representation; never renew its TTL or serve it beyond 300 seconds."""
    entry = CachedPagedFeed.from_cache_value(cache.get(key))
    if entry is None:
        return None
    if not 0 <= _now() - entry.generated_at < CACHE_SECONDS:
        cache.delete(key)
        return None
    return entry


def _strip_validators(response: HttpResponseBase) -> None:
    for header in _VALIDATOR_HEADERS:
        if header in response:
            del response[header]


def _no_store(response: HttpResponseBase) -> HttpResponseBase:
    response["Cache-Control"] = ERROR_CACHE_CONTROL
    _strip_validators(response)
    return response


def _apply_public_headers(response: HttpResponseBase, entry: CachedPagedFeed) -> None:
    response["Cache-Control"] = PUBLIC_CACHE_CONTROL
    response["ETag"] = entry.etag
    response["Age"] = str(entry.age())
    for header in ("Last-Modified", "Expires"):
        if header in response:
            del response[header]


def _require_finalizing_middleware(request: HttpRequest) -> PagedFeedRequestState:
    """Fail closed when the mandatory outermost middleware did not wrap this request."""
    state = getattr(request, REQUEST_STATE_ATTRIBUTE, None)
    if not isinstance(state, PagedFeedRequestState) or paged_feed_middleware_errors(settings.MIDDLEWARE):
        raise ImproperlyConfigured(
            f"Paged feeds require {MIDDLEWARE_PATH} as the first MIDDLEWARE entry "
            "and no Django full-site cache middleware."
        )
    return state


def paged_feed_view(
    request: HttpRequest,
    *,
    slug: str,
    kind: str,
    representation: str,
    audio_format: str | None = None,
) -> HttpResponseBase:
    """Public paged feed endpoint.

    Order: mark the route for the final hook when the middleware is present;
    disabled configuration (explicit no-store 404, since the middleware is
    optional then), mandatory middleware (fail closed), methods (405), fresh
    owner/config/access and canonical path (404), strict query (400) and cursor
    signature/scope validation (400/302) before any cache lookup; then the
    cached or freshly rendered representation. HEAD and conditional requests
    also get the complete GET candidate, so CommonMiddleware and GZipMiddleware
    produce GET's representation headers; preconditions, HEAD body removal and
    cache insertion happen in the final middleware hook.
    """
    marker = getattr(request, REQUEST_STATE_ATTRIBUTE, None)
    if isinstance(marker, PagedFeedRequestState):
        marker.paged = True
    if not feed_pagination_records():
        return _no_store(HttpResponseNotFound(b"Not found", content_type="text/plain"))
    state = _require_finalizing_middleware(request)
    if request.method not in ("GET", "HEAD"):
        return _no_store(HttpResponseNotAllowed(["GET", "HEAD"]))
    try:
        target = admit_paged_feed_request(
            request, slug=slug, kind=kind, representation=representation, audio_format=audio_format
        )
        if target.cursor is not None:
            # Same decoder and semantics as selection: a warm entry never bypasses key removal.
            decode_cursor(target.cursor, target.scope)
        cache_key = paged_feed_cache_key(target)
        entry = _cached_entry(cache_key)
        selection = select_paged_feed(target) if entry is None else None
    except InvalidFeedCursor:
        return _no_store(HttpResponseBadRequest(b"Invalid feed request", content_type="text/plain"))
    except RestartFeedCursor:
        return _no_store(HttpResponseRedirect(target.head_url))
    state.cache_key = cache_key
    state.hit = entry is not None
    if selection is not None:
        rendered = render_paged_feed(target, selection)
        entry = CachedPagedFeed(
            rendered.content, rendered.content_type, paged_feed_etag(rendered.content, target.document_url), _now()
        )
    entry = cast(CachedPagedFeed, entry)
    state.entry = entry
    response = HttpResponse(entry.content, content_type=entry.content_type)
    response["Cache-Control"] = CANDIDATE_CACHE_CONTROL
    state.candidate = response
    return response


def _is_shared_cache_safe(response: HttpResponseBase) -> bool:
    if response.cookies or response.has_header("Set-Cookie"):
        return False
    vary = {token.strip().lower() for token in response.get("Vary", "").split(",") if token.strip()}
    return vary <= PERMITTED_VARY


def _evaluate_preconditions(request: HttpRequest, candidate: HttpResponse, etag: str) -> HttpResponseBase:
    """Django's precondition evaluation (If-Match 412, weak If-None-Match 304), after all other middleware.

    The 304 keeps the candidate's Vary (e.g. Accept-Encoding from GZipMiddleware)
    and cookies; a literal Set-Cookie header is kept as well.
    """
    # Never None when a response is passed.
    response = cast(HttpResponse, get_conditional_response(request, etag=etag, response=candidate))
    if response.status_code == 304 and candidate.has_header("Set-Cookie"):
        response["Set-Cookie"] = candidate["Set-Cookie"]
    return response


def _strip_head_body(response: HttpResponseBase) -> None:
    if isinstance(response, StreamingHttpResponse):
        response.streaming_content = []
    else:
        cast(HttpResponse, response).content = b""


def finalize_paged_feed_response(
    request: HttpRequest, state: PagedFeedRequestState, response: HttpResponseBase
) -> HttpResponseBase:
    """Apply preconditions and the final shared-cache policy after all other middleware.

    Anything but the view's own 200 candidate is an uncached no-store error.
    Preconditions are evaluated here, so a 304 carries the Vary headers the
    representation middleware added; a 412 is a no-store error. Set-Cookie
    (``response.cookies`` or a literal header) or a Vary outside
    Accept-Encoding/Accept-Language on the candidate or the final response makes
    the 200 or 304 private and no-store without validators (cookies and the
    bodyless 304 are kept) and evicts an unsafe warm entry. A safe cold 200 or
    304 stores the full pre-compression 200 entry; hits never renew the TTL.
    HEAD bodies are removed last, after GET's representation headers exist.
    """
    entry = state.entry
    candidate = state.candidate
    if entry is None or candidate is None or response is not candidate or response.status_code != 200:
        response = _no_store(response)
    else:
        response = _evaluate_preconditions(request, candidate, entry.etag)
        if response.status_code not in (200, 304):
            response = _no_store(response)
        elif not (_is_shared_cache_safe(candidate) and _is_shared_cache_safe(response)):
            response["Cache-Control"] = UNSAFE_CACHE_CONTROL
            _strip_validators(response)
            if state.hit:
                cache.delete(cast(str, state.cache_key))
        else:
            _apply_public_headers(response, entry)
            if not state.hit:
                cache.set(cast(str, state.cache_key), entry.as_cache_value(), CACHE_SECONDS)
    if request.method == "HEAD":
        _strip_head_body(response)
    return response
