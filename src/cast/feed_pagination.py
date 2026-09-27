"""Configuration and owner resolution for the opt-in paged feed endpoints.

Parsing is pure; resolution queries the database.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import Http404, HttpRequest
from django.http.request import split_domain_port
from wagtail.models import Page, Site

if TYPE_CHECKING:
    from .models import Blog

SETTING_NAME = "CAST_FEED_PAGINATION"
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 500
FEED_KINDS = ("blog", "podcast")
_REQUIRED_FIELDS = frozenset({"hostname", "port", "blog_path"})
_ALLOWED_FIELDS = _REQUIRED_FIELDS | {"page_size"}
_DNS_LABEL = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")
_FORBIDDEN_PATH_CHARACTERS = re.compile(r"[?#%\\\s\x00-\x1f\x7f]")


@dataclass(frozen=True)
class FeedPaginationRecord:
    """One normalized ``CAST_FEED_PAGINATION`` entry."""

    hostname: str
    port: int
    blog_path: str
    page_size: int = DEFAULT_PAGE_SIZE

    @property
    def slug_segment(self) -> str | None:
        """Last path segment, or None for a Blog at the Site root."""
        return self.blog_path.rstrip("/").rpartition("/")[2] or None


@dataclass(frozen=True)
class FeedOwner:
    """A configured record resolved to its exact Site and Blog or Podcast."""

    record: FeedPaginationRecord
    site: Site
    blog: Blog
    is_podcast: bool


class FeedOwnerError(Exception):
    """A configured record does not resolve to exactly one eligible Blog."""


def normalize_hostname(value: str) -> str | None:
    """Return a lowercased bare hostname without trailing dot, or None if invalid."""
    domain, port = split_domain_port(value)
    if not domain or port:
        return None
    if domain.startswith("["):
        try:
            return f"[{ipaddress.IPv6Address(domain[1:-1]).compressed}]"
        except ValueError:
            return None
    labels = domain.split(".")
    if len(domain) > 253 or not all(_DNS_LABEL.fullmatch(label) for label in labels):
        return None
    return domain


def _exact_int(value: object, minimum: int, maximum: int) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _blog_path_error(value: object) -> str | None:
    if not isinstance(value, str):
        return "blog_path must be a string"
    if not (value.startswith("/") and value.endswith("/")):
        return "blog_path must start and end with '/'"
    if _FORBIDDEN_PATH_CHARACTERS.search(value):
        return "blog_path must not contain a query, fragment, percent escape, backslash or whitespace"
    if value != "/" and any(segment in ("", ".", "..") for segment in value[1:-1].split("/")):
        return "blog_path must not contain empty or dot segments"
    return None


def _parse_record(index: int, raw: object) -> tuple[FeedPaginationRecord | None, list[str]]:
    prefix = f"{SETTING_NAME}[{index}]"
    if not isinstance(raw, dict):
        return None, [f"{prefix} must be a dict"]
    errors: list[str] = []
    keys = set(raw)
    if unknown := sorted(repr(key) for key in keys - _ALLOWED_FIELDS):
        errors.append(f"{prefix} has unknown fields: {', '.join(unknown)}")
    if missing := sorted(_REQUIRED_FIELDS - keys):
        errors.append(f"{prefix} is missing required fields: {', '.join(missing)}")
    hostname = raw.get("hostname")
    hostname = normalize_hostname(hostname) if isinstance(hostname, str) else None
    if "hostname" in keys and hostname is None:
        errors.append(f"{prefix} hostname must be a bare hostname without scheme, port or path")
    port = raw.get("port")
    if "port" in keys and not _exact_int(port, 1, 65535):
        errors.append(f"{prefix} port must be an integer from 1 to 65535")
    blog_path = raw.get("blog_path")
    if "blog_path" in keys and (path_error := _blog_path_error(blog_path)):
        errors.append(f"{prefix} {path_error}")
    page_size = raw.get("page_size", DEFAULT_PAGE_SIZE)
    if not _exact_int(page_size, 1, MAX_PAGE_SIZE):
        errors.append(f"{prefix} page_size must be an integer from 1 to {MAX_PAGE_SIZE}")
    if errors or hostname is None:
        return None, errors
    return FeedPaginationRecord(hostname, cast(int, port), cast(str, blog_path), page_size), []


def validate_feed_pagination(value: object) -> tuple[tuple[FeedPaginationRecord, ...], list[str]]:
    """Normalize the setting without database access; return records and all structural errors."""
    if not isinstance(value, list):
        return (), [f"{SETTING_NAME} must be a list of dicts"]
    records: list[FeedPaginationRecord] = []
    errors: list[str] = []
    for index, raw in enumerate(value):
        record, record_errors = _parse_record(index, raw)
        errors.extend(record_errors)
        if record is not None:
            records.append(record)
    seen_paths: set[tuple[str, int, str]] = set()
    seen_slugs: set[tuple[str, int, str]] = set()
    for record in records:
        target = (record.hostname, record.port, record.blog_path)
        if target in seen_paths:
            errors.append(
                f"{SETTING_NAME} configures {record.hostname}:{record.port}{record.blog_path} more than once"
            )
            continue
        seen_paths.add(target)
        if record.slug_segment is not None:
            slug_key = (record.hostname, record.port, record.slug_segment)
            if slug_key in seen_slugs:
                errors.append(
                    f"{SETTING_NAME} configures more than one blog with slug {record.slug_segment!r} "
                    f"on {record.hostname}:{record.port}"
                )
            seen_slugs.add(slug_key)
    return (tuple(records) if not errors else ()), errors


def feed_pagination_records() -> tuple[FeedPaginationRecord, ...]:
    """Return the configured records, raising ImproperlyConfigured for malformed configuration."""
    records, errors = validate_feed_pagination(getattr(settings, SETTING_NAME, []))
    if errors:
        raise ImproperlyConfigured("; ".join(errors))
    if records and not settings.USE_TZ:
        raise ImproperlyConfigured(f"{SETTING_NAME} requires USE_TZ=True for lossless UTC cursors")
    return records


def _record_label(record: FeedPaginationRecord) -> str:
    return f"{record.hostname}:{record.port}{record.blog_path}"


def resolve_feed_owner(record: FeedPaginationRecord) -> FeedOwner:
    """Resolve an exact Site and a unique Blog at the configured path, without Site fallback."""
    from .models import Blog, Podcast

    label = _record_label(record)
    sites = list(Site.objects.select_related("root_page").filter(hostname=record.hostname, port=record.port)[:2])
    if len(sites) != 1:
        raise FeedOwnerError(f"{label}: no unique Wagtail Site has exactly this hostname and port")
    site = sites[0]
    root = site.root_page
    url_path = root.url_path + record.blog_path[1:]
    page_ids = list(Page.objects.descendant_of(root, inclusive=True).filter(url_path=url_path).values_list("pk")[:2])
    if len(page_ids) != 1:
        raise FeedOwnerError(f"{label}: no unique page exists at this path under the Site root")
    (page_id,) = page_ids[0]
    podcast = Podcast.objects.filter(pk=page_id).first()
    blog = podcast or Blog.objects.filter(pk=page_id).first()
    if blog is None:
        raise FeedOwnerError(f"{label}: the page at this path is not a Blog or Podcast")
    if Blog.objects.descendant_of(root, inclusive=True).filter(slug=blog.slug).exclude(pk=blog.pk).exists():
        raise FeedOwnerError(f"{label}: another Blog on this Site uses slug {blog.slug!r}, so routes are ambiguous")
    return FeedOwner(record=record, site=site, blog=blog, is_podcast=podcast is not None)


def owner_is_public_live(owner: FeedOwner) -> bool:
    """Freshly check that the owner is live, with no direct or inherited view restriction."""
    from .models import Blog

    return Blog.objects.live().public().filter(pk=owner.blog.pk).exists()


def require_public_live_owner(owner: FeedOwner) -> FeedOwner:
    """Return the owner if it may be served publicly right now, or raise 404."""
    if not owner_is_public_live(owner):
        raise Http404("Paged feed owner is not live public content")
    return owner


def request_host_and_port(request: HttpRequest) -> tuple[str, int]:
    """Return the normalized, ALLOWED_HOSTS-validated host and effective port.

    ``get_host`` raises ``DisallowedHost`` and only honors X-Forwarded-Host when
    Django's ``USE_X_FORWARDED_HOST`` is enabled. A missing port is inferred
    from ``is_secure``, which trusts only ``SECURE_PROXY_SSL_HEADER``.
    """
    host = request.get_host()
    domain, port = split_domain_port(host)
    hostname = normalize_hostname(domain)
    if hostname is None:
        raise Http404("Unsupported request host")
    if not port:
        return hostname, 443 if request.is_secure() else 80
    port_number = int(port)
    if not 1 <= port_number <= 65535:
        raise Http404("Unsupported request port")
    return hostname, port_number


def resolve_request_owner(
    request: HttpRequest, *, slug: str, kind: str = "blog", audio_format: str | None = None
) -> FeedOwner:
    """Resolve and freshly authorize the configured owner of a paged feed request, or raise 404.

    Malformed global configuration raises ImproperlyConfigured instead.
    """
    from .models import Audio

    if kind not in FEED_KINDS:
        raise ValueError("Unsupported feed kind")
    records = feed_pagination_records()
    if not records:
        raise Http404("Paged feeds are not configured")
    if kind == "podcast" and audio_format not in Audio.audio_formats:
        raise Http404("Unknown audio format")
    if kind == "blog" and audio_format is not None:
        raise Http404("Blog feeds have no audio format")
    hostname, port = request_host_and_port(request)
    matches: list[FeedOwner] = []
    for record in records:
        if record.hostname != hostname or record.port != port or record.slug_segment not in (None, slug):
            continue
        try:
            owner = resolve_feed_owner(record)
        except FeedOwnerError:
            continue
        if owner.blog.slug == slug:
            matches.append(owner)
    if len(matches) != 1:
        raise Http404("Paged feed is not enabled for this blog")
    owner = matches[0]
    site = Site.find_for_request(request)
    if site is None or site.pk != owner.site.pk:
        raise Http404("Request does not route to the configured Site")
    if kind == "podcast" and not owner.is_podcast:
        raise Http404("Paged podcast feeds require a Podcast")
    return require_public_live_owner(owner)
