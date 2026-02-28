"""Build configuration dicts for the Podlove Web Player.

The Podlove Web Player is used to render podcast episode audio players.
This module assembles a theme-aware configuration dict that includes
color tokens, font families, and player feature toggles. The output
is passed as JSON to the player's JavaScript initialization.

Theme resolution order:
1. ``CAST_PODLOVE_PLAYER_THEMES`` setting overrides (per theme/color scheme)
2. Built-in Bootstrap 5 tokens (light/dark) when ``template_base_dir`` is
   ``"bootstrap5"``
3. ``DEFAULT_PODLOVE_THEME`` fallback
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from collections.abc import Mapping

from django.conf import settings

DEFAULT_PODLOVE_THEME: dict[str, Any] = {
    "tokens": {
        "brand": "#E64415",
        "brandDark": "#235973",
        "brandDarkest": "#1A3A4A",
        "brandLightest": "#E9F1F5",
        "shadeDark": "#807E7C",
        "shadeBase": "#807E7C",
        "contrast": "#000",
        "alt": "#fff",
    },
    "fonts": {
        "ci": {
            "name": "ci",
            "family": [
                "-apple-system",
                "BlinkMacSystemFont",
                "Segoe UI",
                "Roboto",
                "Helvetica",
                "Arial",
                "sans-serif",
                "Apple Color Emoji",
            ],
            "src": [],
            "weight": 800,
        },
        "regular": {
            "name": "regular",
            "family": [
                "-apple-system",
                "BlinkMacSystemFont",
                "Segoe UI",
                "Roboto",
                "Helvetica",
                "Arial",
                "sans-serif",
                "Apple Color Emoji",
            ],
            "src": [],
            "weight": 300,
        },
        "bold": {
            "name": "bold",
            "family": [
                "-apple-system",
                "BlinkMacSystemFont",
                "Segoe UI",
                "Roboto",
                "Helvetica",
                "Arial",
                "sans-serif",
                "Apple Color Emoji",
            ],
            "src": [],
            "weight": 700,
        },
    },
}

BOOTSTRAP5_LIGHT_TOKENS: dict[str, str] = {
    "brand": "#d97706",
    "brandDark": "#b45309",
    "brandDarkest": "#2d2a26",
    "brandLightest": "#fef3c7",
    "shadeDark": "#6b6560",
    "shadeBase": "#6b6560",
    "contrast": "#2d2a26",
    "alt": "#ffffff",
}

BOOTSTRAP5_DARK_TOKENS: dict[str, str] = {
    "brand": "#fbbf24",
    "brandDark": "#f59e0b",
    "brandDarkest": "#451a03",
    "brandLightest": "#451a03",
    "shadeDark": "#a8a29e",
    "shadeBase": "#a8a29e",
    "contrast": "#fafaf9",
    "alt": "#292524",
}

BOOTSTRAP5_FONTS: dict[str, Any] = {
    "ci": {
        "name": "ci",
        "family": [
            "Inter",
            "-apple-system",
            "BlinkMacSystemFont",
            "Segoe UI",
            "Roboto",
            "Helvetica",
            "Arial",
            "sans-serif",
            "Apple Color Emoji",
        ],
        "src": [],
        "weight": 600,
    },
    "regular": {
        "name": "regular",
        "family": [
            "Inter",
            "-apple-system",
            "BlinkMacSystemFont",
            "Segoe UI",
            "Roboto",
            "Helvetica",
            "Arial",
            "sans-serif",
            "Apple Color Emoji",
        ],
        "src": [],
        "weight": 400,
    },
    "bold": {
        "name": "bold",
        "family": [
            "Inter",
            "-apple-system",
            "BlinkMacSystemFont",
            "Segoe UI",
            "Roboto",
            "Helvetica",
            "Arial",
            "sans-serif",
            "Apple Color Emoji",
        ],
        "src": [],
        "weight": 700,
    },
}

BASE_PLAYER_CONFIG: dict[str, Any] = {
    "activeTab": None,
    "subscribe-button": None,
    "share": {
        "channels": ["facebook", "twitter", "whats-app", "linkedin", "pinterest", "xing", "mail", "link"],
        "sharePlaytime": True,
    },
    "related-episodes": {"source": "disabled", "value": None},
    "version": 5,
}


def build_podlove_player_config(*, template_base_dir: str | None, color_scheme: str | None) -> dict[str, Any]:
    """Return a Podlove Web Player configuration dict for the given theme and color scheme.

    The returned dict contains ``theme`` (color tokens and fonts), share
    channels, and player version metadata. It is serialized to JSON and
    passed to the ``<podlove-web-player>`` element in templates.
    """
    scheme = _normalize_color_scheme(color_scheme)
    theme = _resolve_theme_config(template_base_dir=template_base_dir, color_scheme=scheme)
    config = deepcopy(BASE_PLAYER_CONFIG)
    config["theme"] = theme
    return config


def _normalize_color_scheme(color_scheme: str | None) -> str:
    if not color_scheme:
        return "light"
    scheme = color_scheme.strip().lower()
    return scheme if scheme in {"light", "dark"} else "light"


def _resolve_theme_config(*, template_base_dir: str | None, color_scheme: str) -> dict[str, Any]:
    base_theme = deepcopy(DEFAULT_PODLOVE_THEME)
    theme_overrides = _get_theme_overrides()

    if template_base_dir == "bootstrap5":
        tokens = BOOTSTRAP5_DARK_TOKENS if color_scheme == "dark" else BOOTSTRAP5_LIGHT_TOKENS
        base_theme["tokens"].update(tokens)
        base_theme["fonts"].update(deepcopy(BOOTSTRAP5_FONTS))

    override = _select_override(theme_overrides, template_base_dir, color_scheme)
    if not override:
        return base_theme

    if "tokens" in override:
        base_theme["tokens"].update(override["tokens"])
    if "fonts" in override:
        base_theme["fonts"].update(override["fonts"])

    return base_theme


def _get_theme_overrides() -> Mapping[str, Any]:
    return getattr(settings, "CAST_PODLOVE_PLAYER_THEMES", {})


def _select_override(
    overrides: Mapping[str, Any], template_base_dir: str | None, color_scheme: str
) -> Mapping[str, Any]:
    theme_override: Mapping[str, Any] | None = None
    if template_base_dir and template_base_dir in overrides:
        theme_override = overrides[template_base_dir]
    elif "default" in overrides:
        theme_override = overrides["default"]

    if not theme_override:
        return {}

    if "light" in theme_override or "dark" in theme_override:
        return theme_override.get(color_scheme) or theme_override.get("light") or {}

    return theme_override
