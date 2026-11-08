from __future__ import annotations

import math
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest
from wagtail.models import Site

from cast.models.voxhelm_settings import VoxhelmSettings

from ..setting_resolution import (
    SETTING_SOURCE_DJANGO,
    SETTING_SOURCE_SITE,
    environment_setting,
    parse_bool_setting,
    resolve_layered_setting,
)

API_BASE_SETTING = "CAST_VOXHELM_API_BASE"
API_KEY_SETTING = "CAST_VOXHELM_API_KEY"
DEPLOYMENT_CREDENTIAL_NAMES = (API_BASE_SETTING, API_KEY_SETTING)

# ``CAST_VOXHELM_API_BASE`` is deliberately absent: the base URL is deployment
# configuration only (Django setting or environment variable).
SITE_SETTING_FIELD_MAP = {
    "CAST_VOXHELM_API_KEY": "api_token",
    "CAST_VOXHELM_MODEL": "model",
    "CAST_VOXHELM_LANGUAGE": "language",
    "CAST_VOXHELM_DIARIZATION_ENABLED": "diarization_enabled",
    "CAST_VOXHELM_KNOWN_SPEAKER_ENABLED": "known_speaker_enabled",
}


def get_site_setting_value(name: str, request_or_site: HttpRequest | Site | None) -> object:
    field_name = SITE_SETTING_FIELD_MAP.get(name)
    if field_name is None or request_or_site is None:
        return None

    if isinstance(request_or_site, Site):
        site_settings = VoxhelmSettings.for_site(request_or_site)
    else:
        site_settings = VoxhelmSettings.for_request(request_or_site)
    value = getattr(site_settings, field_name, "")
    if isinstance(value, str):
        return value.strip()
    return value


def resolve_setting(
    name: str, default: object = None, *, request_or_site: HttpRequest | Site | None = None
) -> tuple[object, str]:
    """Return ``(value, source)`` for a Voxhelm setting.

    ``source`` is one of ``SETTING_SOURCES``: the Wagtail site setting, a Django
    setting, an environment variable, or the caller's default. Empty values
    (``None``/``""``) at a level fall through to the next level, so a nullable
    site boolean left unset inherits the Django setting or environment variable.
    """
    if name == API_KEY_SETTING:
        # A site token overrides the deployment key; the base URL never comes from the site.
        site_token = get_site_setting_value(name, request_or_site)
        if site_token not in {None, ""}:
            return site_token, SETTING_SOURCE_SITE
    if name in DEPLOYMENT_CREDENTIAL_NAMES:
        # Any deployment credential at a level selects that level's pair, even if incomplete.
        django_pair = {key: getattr(settings, key, None) for key in DEPLOYMENT_CREDENTIAL_NAMES}
        if any(value not in {None, ""} for value in django_pair.values()):
            return django_pair[name], SETTING_SOURCE_DJANGO
        return environment_setting(name, default)
    return resolve_layered_setting(name, get_site_setting_value(name, request_or_site), default)


def get_setting(name: str, default: object = None, *, request_or_site: HttpRequest | Site | None = None) -> object:
    return resolve_setting(name, default, request_or_site=request_or_site)[0]


def validate_api_base(value: object) -> str:
    """Return the stripped Voxhelm API base, or raise ``ImproperlyConfigured``.

    Only absolute ``http``/``https`` URLs with a host are accepted. Userinfo,
    query strings and fragments are rejected: ``/v1`` and job paths are appended
    to the base, so a ``#`` or ``?`` would silently move the real request path.
    """
    if not isinstance(value, str) or not value.strip():
        raise ImproperlyConfigured(
            f"{API_BASE_SETTING} must be configured as a Django setting or environment variable."
        )
    api_base = value.strip()
    try:
        parts = urlsplit(api_base)
        hostname = parts.hostname
        parts.port  # noqa: B018 - raises ValueError for an invalid port
    except ValueError as exc:
        raise ImproperlyConfigured(f"{API_BASE_SETTING} is not a valid URL.") from exc
    if parts.scheme not in {"http", "https"} or not hostname:
        raise ImproperlyConfigured(f"{API_BASE_SETTING} must be an absolute http:// or https:// URL with a host.")
    if "@" in parts.netloc:
        raise ImproperlyConfigured(f"{API_BASE_SETTING} must not contain credentials (user info).")
    if "#" in api_base or parts.fragment:
        raise ImproperlyConfigured(f"{API_BASE_SETTING} must not contain a fragment.")
    if "?" in api_base or parts.query:
        raise ImproperlyConfigured(f"{API_BASE_SETTING} must not contain a query string.")
    if any(ord(character) < 33 or character == "\\" for character in api_base):
        raise ImproperlyConfigured(
            f"{API_BASE_SETTING} must not contain whitespace, control characters or backslashes."
        )
    return api_base


def deployment_api_base() -> object:
    """Return the configured deployment API base (Django setting, else environment)."""
    return resolve_setting(API_BASE_SETTING)[0]


def voxhelm_configured(*, request_or_site: HttpRequest | Site | None = None) -> bool:
    """True when the Voxhelm API base and key both resolve non-empty from the same configuration level."""
    for name in ("CAST_VOXHELM_API_BASE", "CAST_VOXHELM_API_KEY"):
        value = get_setting(name, request_or_site=request_or_site)
        if not isinstance(value, str) or not value.strip():
            return False
    return True


def require_setting(name: str, *, request_or_site: HttpRequest | Site | None = None) -> str:
    value = get_setting(name, request_or_site=request_or_site)
    if not isinstance(value, str) or not value.strip():
        raise ImproperlyConfigured(f"{name} must be configured as a Django setting or environment variable.")
    return value.strip()


def validate_duration(name: str, value: object) -> float:
    """Accept positive finite durations up to one day, including fractional seconds."""
    try:
        duration = float(str(value))
        if isinstance(value, bool) or not math.isfinite(duration) or not 0 < duration <= 86400:
            raise ValueError
    except (TypeError, ValueError, OverflowError) as exc:
        raise ImproperlyConfigured(
            f"{name} must be a finite duration greater than 0 and at most 86400 seconds."
        ) from exc
    return duration


def get_float_setting(name: str, default: float, *, request_or_site: HttpRequest | Site | None = None) -> float:
    return validate_duration(name, get_setting(name, default, request_or_site=request_or_site))


def resolve_bool_setting(
    name: str, default: bool = False, *, request_or_site: HttpRequest | Site | None = None
) -> tuple[bool, str]:
    """Return the parsed boolean value of a Voxhelm setting and the level it came from."""
    value, source = resolve_setting(name, default, request_or_site=request_or_site)
    return parse_bool_setting(name, value, source, default)


def get_bool_setting(name: str, default: bool = False, *, request_or_site: HttpRequest | Site | None = None) -> bool:
    return resolve_bool_setting(name, default, request_or_site=request_or_site)[0]
