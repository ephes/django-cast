"""Django system checks for django-cast."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.checks import Warning, register

# Source extensions to consider
SOURCE_EXTENSIONS = frozenset({".ts", ".tsx", ".js", ".jsx", ".vue", ".css", ".scss", ".sass"})


def _newest_source_mtime(source_dir: Path) -> float | None:
    """Return the mtime of the most recently modified source file, or None."""
    newest = 0.0
    found = False
    for path in source_dir.rglob("*"):
        if path.is_file() and path.suffix in SOURCE_EXTENSIONS:
            mtime = path.stat().st_mtime
            if mtime > newest:
                newest = mtime
            found = True
    return newest if found else None


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
def check_asset_freshness(app_configs, **kwargs):  # type: ignore[no-untyped-def]
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
