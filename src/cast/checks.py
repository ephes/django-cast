"""Django system checks for django-cast."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from django.apps import AppConfig
from django.conf import settings
from django.core.checks import Error, Warning, register

from cast.apps import CAST_MIDDLEWARE
from cast.post_body_blocks import validate_post_body_block_setting

# Source extensions to consider
SOURCE_EXTENSIONS = frozenset({".ts", ".tsx", ".js", ".jsx", ".vue", ".css", ".scss", ".sass"})

CAST_SETTING_TYPES: tuple[tuple[str, type], ...] = (
    ("CAST_COMMENTS_ENABLED", bool),
    ("CAST_CUSTOM_THEMES", list),
    ("CAST_FOLLOW_LINKS", dict),
    ("CAST_FILTERSET_FACETS", list),
    ("CAST_IMAGE_FORMATS", list),
    ("CAST_REGULAR_IMAGE_SLOT_DIMENSIONS", list),
    ("CAST_GALLERY_IMAGE_SLOT_DIMENSIONS", list),
    ("CAST_REPOSITORY", str),
    ("CAST_PODLOVE_PLAYER_THEMES", dict),
    ("CAST_AUDIO_PLAYER", str),
    ("CAST_PLAYER_INLINE_TRANSCRIPT_MAX_BYTES", int),
)

VALID_AUDIO_PLAYERS = frozenset({"podlove", "custom"})


def _newest_source_mtime(source_dir: Path) -> float | None:
    """Return the mtime of the most recently modified source file, or None."""
    mtimes = [p.stat().st_mtime for p in source_dir.rglob("*") if p.is_file() and p.suffix in SOURCE_EXTENSIONS]
    return max(mtimes) if mtimes else None


def _find_stale_assets(base_dir: Path) -> list[str]:
    """Check all known source→manifest pairs under base_dir and return warnings."""
    stale: list[str] = []

    # django-cast: javascript/src → src/cast/static/cast/vite/manifest.json
    pairs: list[tuple[Path, Path]] = [
        (base_dir / "javascript" / "src", base_dir / "src" / "cast" / "static" / "cast" / "vite" / "manifest.json"),
    ]

    for source_dir, manifest in pairs:
        if not source_dir.is_dir() or not manifest.is_file():
            continue
        src_mtime = _newest_source_mtime(source_dir)
        if src_mtime is not None and src_mtime > manifest.stat().st_mtime:
            stale.append(f"{source_dir} is newer than {manifest.name} — run 'just js-build-vite'")

    return stale


@register("cast")
def check_cast_setting_types(
    app_configs: Sequence[AppConfig] | None = None,
    databases: Sequence[str] | None = None,
    **kwargs: Any,
) -> list[Error]:
    """Validate basic types for core CAST_* settings."""
    errors: list[Error] = []

    for setting_name, expected_type in CAST_SETTING_TYPES:
        value: Any = getattr(settings, setting_name, None)
        if value is None:
            continue
        if not isinstance(value, expected_type):
            errors.append(
                Error(
                    f"{setting_name} must be of type {expected_type.__name__}.",
                    id="cast.E001",
                )
            )

    return errors


@register("cast")
def check_cast_audio_player_settings(
    app_configs: Sequence[AppConfig] | None = None,
    databases: Sequence[str] | None = None,
    **kwargs: Any,
) -> list[Error]:
    """Validate the values of the custom-audio-player settings."""
    errors: list[Error] = []

    player = getattr(settings, "CAST_AUDIO_PLAYER", None)
    if player is not None and player not in VALID_AUDIO_PLAYERS:
        valid = ", ".join(sorted(VALID_AUDIO_PLAYERS))
        errors.append(
            Error(
                f"CAST_AUDIO_PLAYER must be one of: {valid}.",
                id="cast.E005",
            )
        )

    cap = getattr(settings, "CAST_PLAYER_INLINE_TRANSCRIPT_MAX_BYTES", None)
    # ``isinstance(True, int)`` is True, so booleans must be excluded explicitly.
    if cap is not None and (isinstance(cap, bool) or not isinstance(cap, int) or cap <= 0):
        errors.append(
            Error(
                "CAST_PLAYER_INLINE_TRANSCRIPT_MAX_BYTES must be a positive integer.",
                id="cast.E006",
            )
        )

    return errors


@register("cast")
def check_post_body_block_setting(
    app_configs: Sequence[AppConfig] | None = None,
    databases: Sequence[str] | None = None,
    **kwargs: Any,
) -> list[Error]:
    """Validate CAST_POST_BODY_BLOCKS custom block factories."""
    return [
        Error(
            message,
            hint="Use dotted no-argument factories returning (name, wagtail.blocks.Block).",
            id="cast.E004",
        )
        for message in validate_post_body_block_setting()
    ]


@register("cast")
def check_asset_freshness(
    app_configs: Sequence[AppConfig] | None = None,
    databases: Sequence[str] | None = None,
    **kwargs: Any,
) -> list[Warning]:
    """Warn when Vite assets are stale (DEBUG mode only)."""
    warnings: list[Warning] = []

    if not getattr(settings, "DEBUG", False):
        return warnings

    # Try to find the repo root by looking for pyproject.toml above src/cast/
    cast_dir = Path(__file__).resolve().parent  # src/cast/
    repo_root = cast_dir.parent.parent  # repo root (above src/)
    if not (repo_root / "pyproject.toml").is_file():
        return warnings  # not a development checkout

    for message in _find_stale_assets(repo_root):
        warnings.append(
            Warning(
                message,
                hint="Rebuild with 'just js-build-vite' or 'just js-build-all'.",
                id="cast.W001",
            )
        )

    return warnings


@register("cast")
def check_cast_comments_ordering(
    app_configs: Sequence[AppConfig] | None = None,
    databases: Sequence[str] | None = None,
    **kwargs: Any,
) -> list[Error]:
    """Ensure cast comments app is loaded before django_comments."""
    installed_apps = list(getattr(settings, "INSTALLED_APPS", []))
    cast_comments_app = "cast.comments.apps.CastCommentsConfig"

    django_comments_index = next(
        (
            index
            for index, app_name in enumerate(installed_apps)
            if app_name == "django_comments" or app_name.startswith("django_comments.")
        ),
        None,
    )
    cast_comments_index = next(
        (index for index, app_name in enumerate(installed_apps) if app_name in {"cast.comments", cast_comments_app}),
        None,
    )
    if django_comments_index is None or cast_comments_index is None or cast_comments_index < django_comments_index:
        return []

    return [
        Error(
            f"'{cast_comments_app}' must appear before 'django_comments' in INSTALLED_APPS.",
            hint=f"Move '{cast_comments_app}' before 'django_comments' in settings.INSTALLED_APPS.",
            id="cast.E002",
        )
    ]


@register("cast")
def check_cast_required_middleware(
    app_configs: Sequence[AppConfig] | None = None,
    databases: Sequence[str] | None = None,
    **kwargs: Any,
) -> list[Error]:
    """Ensure middleware required by django-cast is present."""
    configured_middleware = set(getattr(settings, "MIDDLEWARE", []))
    missing_middleware = [middleware for middleware in CAST_MIDDLEWARE if middleware not in configured_middleware]
    if not missing_middleware:
        return []

    missing_middleware_str = ", ".join(missing_middleware)
    return [
        Error(
            f"settings.MIDDLEWARE is missing required django-cast middleware: {missing_middleware_str}.",
            hint="Add all entries from cast.apps.CAST_MIDDLEWARE to settings.MIDDLEWARE.",
            id="cast.E003",
        )
    ]
