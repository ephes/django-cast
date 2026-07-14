"""Django system checks for django-cast."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from django.apps import AppConfig, apps
from django.conf import settings
from django.core.checks import Error, Warning, register

from cast import appsettings
from cast.appsettings import CAST_SETTING_REGISTRY
from cast.apps import CAST_MIDDLEWARE
from cast.post_body_blocks import validate_post_body_block_setting

# Source extensions to consider
SOURCE_EXTENSIONS = frozenset({".ts", ".tsx", ".js", ".jsx", ".vue", ".css", ".scss", ".sass"})

CAST_SETTING_TYPES: tuple[tuple[str, type], ...] = tuple(
    (name, cast_setting.check_type)
    for name, cast_setting in CAST_SETTING_REGISTRY.items()
    if cast_setting.check_type is not None
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
    """Validate the value of the custom-audio-player setting."""
    errors: list[Error] = []

    # Read through the central accessor so an unset value resolves to the
    # registry default; an explicit ``CAST_AUDIO_PLAYER = None`` still skips
    # validation as before.
    player = appsettings.CAST_AUDIO_PLAYER
    if player is not None and player not in VALID_AUDIO_PLAYERS:
        valid = ", ".join(sorted(VALID_AUDIO_PLAYERS))
        errors.append(
            Error(
                f"CAST_AUDIO_PLAYER must be one of: {valid}.",
                id="cast.E005",
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
def check_cast_comments_author_edits_session_backend(
    app_configs: Sequence[AppConfig] | None = None,
    databases: Sequence[str] | None = None,
    **kwargs: Any,
) -> list[Error]:
    """Anonymous comment self-editing requires a server-side session backend.

    The owned-comment-ids list lives in the session; under ``signed_cookies`` it
    would travel in the client cookie (readable, non-revocable). The feature is
    optional, so this is a hard requirement with no opt-out.
    """
    from cast.comments import appsettings as comment_appsettings
    from cast.comments import author_edits

    if comment_appsettings.ALLOW_AUTHOR_EDITS and author_edits.uses_signed_cookie_sessions():
        return [
            Error(
                "CAST_COMMENTS_ALLOW_AUTHOR_EDITS requires a server-side session backend; "
                "the 'signed_cookies' SESSION_ENGINE is not allowed.",
                hint="Use a server-side SESSION_ENGINE such as 'django.contrib.sessions.backends.db'.",
                id="cast.E006",
            )
        ]
    return []


@register("cast")
def check_cast_comments_author_edits_tunables(
    app_configs: Sequence[AppConfig] | None = None,
    databases: Sequence[str] | None = None,
    **kwargs: Any,
) -> list[Error]:
    """Validate the numeric author-edit tunables are non-negative integers.

    These are coerced with ``int()`` at runtime, so a non-integer value would
    otherwise surface as an opaque runtime error, and a negative value would give
    surprising list-slicing/timeout behaviour.
    """
    errors: list[Error] = []
    # ``OWNED_IDS_CAP`` 0 means "no cap", ``AUTHOR_EDIT_WINDOW`` 0 means disabled,
    # and ``EDIT_RATE_LIMIT`` 0 means "disabled"; the rate window must be positive.
    for name, minimum in (
        ("CAST_COMMENTS_OWNED_IDS_CAP", 0),
        ("CAST_COMMENTS_AUTHOR_EDIT_WINDOW", 0),
        ("CAST_COMMENTS_EDIT_RATE_LIMIT", 0),
        ("CAST_COMMENTS_EDIT_RATE_WINDOW", 1),
    ):
        value = getattr(settings, name, None)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            errors.append(
                Error(
                    f"{name} must be an integer >= {minimum}.",
                    id="cast.E007",
                )
            )
    return errors


@register("cast")
def check_cast_comments_author_edits_requires_sessions(
    app_configs: Sequence[AppConfig] | None = None,
    databases: Sequence[str] | None = None,
    **kwargs: Any,
) -> list[Error]:
    """Anonymous comment self-editing relies on ``request.session``.

    Without the sessions app and middleware the ownership-recording and
    edit/delete paths would raise at runtime, so require both when the feature is
    enabled.
    """
    from cast.comments import appsettings as comment_appsettings

    if not comment_appsettings.ALLOW_AUTHOR_EDITS:
        return []
    errors: list[Error] = []
    # ``apps.is_installed`` resolves the app by name, so it accepts both the
    # plain ``"django.contrib.sessions"`` string and the ``SessionsConfig``
    # AppConfig path in INSTALLED_APPS.
    if not apps.is_installed("django.contrib.sessions"):
        errors.append(
            Error(
                "CAST_COMMENTS_ALLOW_AUTHOR_EDITS requires 'django.contrib.sessions' in INSTALLED_APPS.",
                id="cast.E008",
            )
        )
    middleware = getattr(settings, "MIDDLEWARE", [])
    if not any(str(m).endswith("SessionMiddleware") for m in middleware):
        errors.append(
            Error(
                "CAST_COMMENTS_ALLOW_AUTHOR_EDITS requires a session middleware (e.g. "
                "'django.contrib.sessions.middleware.SessionMiddleware') in MIDDLEWARE.",
                id="cast.E008",
            )
        )
    return errors


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
