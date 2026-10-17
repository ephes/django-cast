"""Layered resolution of site-overridable settings.

A leaf module without model imports, so both the Wagtail site-settings models
and ``cast.voxhelm`` can use it without an import cycle during ``cast.models``
initialisation.
"""

from __future__ import annotations

import os

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

TRUE_SETTING_VALUES = {"1", "true", "yes", "on"}
FALSE_SETTING_VALUES = {"0", "false", "no", "off"}
SETTING_SOURCE_SITE = "site"
SETTING_SOURCE_DJANGO = "django"
SETTING_SOURCE_ENVIRONMENT = "environment"
SETTING_SOURCE_DEFAULT = "default"
SETTING_SOURCES = (SETTING_SOURCE_SITE, SETTING_SOURCE_DJANGO, SETTING_SOURCE_ENVIRONMENT, SETTING_SOURCE_DEFAULT)


def resolve_layered_setting(name: str, site_value: object, default: object = None) -> tuple[object, str]:
    """Return ``(value, source)`` from the site value, a Django setting, the environment, or ``default``.

    Empty values (``None``/``""``) fall through to the next level, so a nullable site
    field left unset inherits the Django setting or environment variable.
    """
    if site_value not in {None, ""}:
        return site_value, SETTING_SOURCE_SITE
    value = getattr(settings, name, None)
    if value not in {None, ""}:
        return value, SETTING_SOURCE_DJANGO
    return environment_setting(name, default)


def environment_setting(name: str, default: object = None) -> tuple[object, str]:
    if name in os.environ:
        return os.environ[name], SETTING_SOURCE_ENVIRONMENT
    return default, SETTING_SOURCE_DEFAULT


def parse_bool_setting(name: str, value: object, source: str, default: bool) -> tuple[bool, str]:
    """Parse a resolved setting value as a boolean; blank strings mean ``default``."""
    if isinstance(value, bool):
        return value, source
    if isinstance(value, int) and value in {0, 1}:
        return bool(value), source
    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized:
            return default, SETTING_SOURCE_DEFAULT
        if normalized in TRUE_SETTING_VALUES:
            return True, source
        if normalized in FALSE_SETTING_VALUES:
            return False, source
    raise ImproperlyConfigured(
        f"{name} must be configured as a boolean value: one of 1, true, yes, on, 0, false, no, or off."
    )
