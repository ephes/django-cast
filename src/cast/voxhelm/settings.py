from __future__ import annotations

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

SITE_SETTING_FIELD_MAP = {
    "CAST_VOXHELM_API_BASE": "api_base",
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
    credential_names = ("CAST_VOXHELM_API_BASE", "CAST_VOXHELM_API_KEY")
    if name in credential_names:
        # Any credential at a level selects the entire pair, even if incomplete.
        site_pair = {key: get_site_setting_value(key, request_or_site) for key in credential_names}
        if any(value not in {None, ""} for value in site_pair.values()):
            return site_pair[name], SETTING_SOURCE_SITE
        django_pair = {key: getattr(settings, key, None) for key in credential_names}
        if any(value not in {None, ""} for value in django_pair.values()):
            return django_pair[name], SETTING_SOURCE_DJANGO
        return environment_setting(name, default)
    return resolve_layered_setting(name, get_site_setting_value(name, request_or_site), default)


def get_setting(name: str, default: object = None, *, request_or_site: HttpRequest | Site | None = None) -> object:
    return resolve_setting(name, default, request_or_site=request_or_site)[0]


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


def get_float_setting(name: str, default: float, *, request_or_site: HttpRequest | Site | None = None) -> float:
    value = get_setting(name, default, request_or_site=request_or_site)
    try:
        return float(str(value))
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(
            f"{name} must be configured as a numeric value in seconds through a Django setting or environment variable."
        ) from exc


def resolve_bool_setting(
    name: str, default: bool = False, *, request_or_site: HttpRequest | Site | None = None
) -> tuple[bool, str]:
    """Return the parsed boolean value of a Voxhelm setting and the level it came from."""
    value, source = resolve_setting(name, default, request_or_site=request_or_site)
    return parse_bool_setting(name, value, source, default)


def get_bool_setting(name: str, default: bool = False, *, request_or_site: HttpRequest | Site | None = None) -> bool:
    return resolve_bool_setting(name, default, request_or_site=request_or_site)[0]
