from __future__ import annotations

import os

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest
from wagtail.models import Site

from cast.models.voxhelm_settings import VoxhelmSettings

SITE_SETTING_FIELD_MAP = {
    "CAST_VOXHELM_API_BASE": "api_base",
    "CAST_VOXHELM_API_KEY": "api_token",
    "CAST_VOXHELM_MODEL": "model",
    "CAST_VOXHELM_LANGUAGE": "language",
    "CAST_VOXHELM_DIARIZATION_ENABLED": "diarization_enabled",
    "CAST_VOXHELM_KNOWN_SPEAKER_ENABLED": "known_speaker_enabled",
}
TRUE_SETTING_VALUES = {"1", "true", "yes", "on"}
FALSE_SETTING_VALUES = {"0", "false", "no", "off"}


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


def get_setting(name: str, default: object = None, *, request_or_site: HttpRequest | Site | None = None) -> object:
    site_value = get_site_setting_value(name, request_or_site)
    if site_value not in {None, ""}:
        return site_value
    value = getattr(settings, name, None)
    if value not in {None, ""}:
        return value
    return os.getenv(name, default)


def voxhelm_configured(*, request_or_site: HttpRequest | Site | None = None) -> bool:
    """True when the Voxhelm API base and key both resolve non-empty through the settings chain."""
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


def get_float_setting(name: str, default: float, *, request_or_site: HttpRequest | Site | None = None) -> float:
    value = get_setting(name, default, request_or_site=request_or_site)
    try:
        return float(str(value))
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(
            f"{name} must be configured as a numeric value in seconds through a Django setting or environment variable."
        ) from exc


def get_bool_setting(name: str, default: bool = False, *, request_or_site: HttpRequest | Site | None = None) -> bool:
    value = get_setting(name, default, request_or_site=request_or_site)
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized:
            return default
        if normalized in TRUE_SETTING_VALUES:
            return True
        if normalized in FALSE_SETTING_VALUES:
            return False
    raise ImproperlyConfigured(
        f"{name} must be configured as a boolean value: one of 1, true, yes, on, 0, false, no, or off."
    )
