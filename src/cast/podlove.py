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

from collections.abc import Iterator, Mapping
from copy import deepcopy
from typing import Any

from cast import appsettings

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


_COLOR_SCHEMES = ("light", "dark")
_THEME_SECTIONS = ("tokens", "fonts")


def invalid_podlove_theme_override_paths() -> Iterator[str]:
    """Yield malformed nested mappings for Django's configuration check."""
    overrides = appsettings.CAST_PODLOVE_PLAYER_THEMES
    if not isinstance(overrides, Mapping):
        return  # The generic setting check handles the outer type.

    for name, theme in overrides.items():
        theme_path = f"CAST_PODLOVE_PLAYER_THEMES[{name!r}]"
        if not isinstance(theme, Mapping):
            yield theme_path
            continue
        entries: Iterator[tuple[str, Any]]
        if any(scheme in theme for scheme in _COLOR_SCHEMES):
            entries = ((f"{theme_path}[{scheme!r}]", theme[scheme]) for scheme in _COLOR_SCHEMES if scheme in theme)
        else:
            entries = iter(((theme_path, theme),))
        for path, entry in entries:
            if not isinstance(entry, Mapping):
                yield path
                continue
            for section in _THEME_SECTIONS:
                if section in entry and not isinstance(entry[section], Mapping):
                    yield f"{path}[{section!r}]"


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
    return scheme if scheme in _COLOR_SCHEMES else "light"


def _resolve_theme_config(*, template_base_dir: str | None, color_scheme: str) -> dict[str, Any]:
    base_theme = deepcopy(DEFAULT_PODLOVE_THEME)
    theme_overrides = appsettings.CAST_PODLOVE_PLAYER_THEMES

    if template_base_dir == "bootstrap5":
        tokens = BOOTSTRAP5_DARK_TOKENS if color_scheme == "dark" else BOOTSTRAP5_LIGHT_TOKENS
        base_theme["tokens"].update(tokens)
        base_theme["fonts"].update(deepcopy(BOOTSTRAP5_FONTS))

    override = _select_override(theme_overrides, template_base_dir, color_scheme)
    for section in _THEME_SECTIONS:
        values = override.get(section)
        if isinstance(values, Mapping):
            base_theme[section].update(deepcopy(dict(values)))

    return base_theme


def _select_override(
    overrides: Mapping[str, Any], template_base_dir: str | None, color_scheme: str
) -> Mapping[str, Any]:
    if not isinstance(overrides, Mapping):
        return {}
    theme_override = (
        overrides.get(template_base_dir)
        if template_base_dir and template_base_dir in overrides
        else overrides.get("default")
    )
    if not isinstance(theme_override, Mapping):
        return {}

    if any(scheme in theme_override for scheme in _COLOR_SCHEMES):
        selected = theme_override.get(color_scheme)
        if isinstance(selected, Mapping) and selected:
            return selected
        light = theme_override.get("light")
        return light if isinstance(light, Mapping) else {}

    return theme_override
