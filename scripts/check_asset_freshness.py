#!/usr/bin/env python3
"""
Check whether built assets are stale compared to their source files.

Compares the newest source-file mtime against the Vite manifest mtime.
If any source file is newer than the manifest, the build is stale.

Usage:
    # django-cast (auto-detected defaults)
    python scripts/check_asset_freshness.py

    # Explicit paths (for theme repos)
    python scripts/check_asset_freshness.py \
        --source-dir javascript/src \
        --manifest cast_bootstrap5/static/cast_bootstrap5/vite/manifest.json

    # Also check SCSS → CSS freshness
    python scripts/check_asset_freshness.py \
        --source-dir javascript/src \
        --manifest cast_bootstrap5/static/cast_bootstrap5/vite/manifest.json \
        --source-dir cast_bootstrap5/static/cast_bootstrap5/scss \
        --manifest cast_bootstrap5/static/cast_bootstrap5/css/bootstrap5/cast.css

Exit code 0 = fresh, 1 = stale, 2 = configuration error (missing args or no detectable pairs).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Source extensions to consider
SOURCE_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".vue", ".css", ".scss", ".sass"}


def newest_source_mtime(source_dir: Path) -> float | None:
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


def check_freshness(source_dir: Path, manifest: Path) -> tuple[bool, str]:
    """Check if built assets are fresh.

    Returns (is_fresh, message).
    """
    if not source_dir.is_dir():
        return False, f"Source directory not found: {source_dir}"

    if not manifest.is_file():
        return False, f"Manifest/built file not found: {manifest}"

    src_mtime = newest_source_mtime(source_dir)
    if src_mtime is None:
        return True, f"No source files found in {source_dir}"

    built_mtime = manifest.stat().st_mtime
    if src_mtime > built_mtime:
        return False, f"Assets are STALE: source in {source_dir} is newer than {manifest}"

    return True, f"Assets are fresh: {source_dir} → {manifest}"


def detect_pairs(repo_root: Path) -> list[tuple[Path, Path]]:
    """Auto-detect source/manifest pairs for the current repository."""
    pairs: list[tuple[Path, Path]] = []

    # django-cast: javascript/src → src/cast/static/cast/vite/manifest.json
    js_src = repo_root / "javascript" / "src"
    vite_manifest = repo_root / "src" / "cast" / "static" / "cast" / "vite" / "manifest.json"
    if js_src.is_dir() and vite_manifest.is_file():
        pairs.append((js_src, vite_manifest))

    # cast-bootstrap5 pattern
    bs5_src = repo_root / "javascript" / "src"
    bs5_manifest = repo_root / "cast_bootstrap5" / "static" / "cast_bootstrap5" / "vite" / "manifest.json"
    if bs5_src.is_dir() and bs5_manifest.is_file():
        pairs.append((bs5_src, bs5_manifest))

    # cast-bootstrap5 SCSS
    scss_src = repo_root / "cast_bootstrap5" / "static" / "cast_bootstrap5" / "scss"
    css_built = repo_root / "cast_bootstrap5" / "static" / "cast_bootstrap5" / "css" / "bootstrap5" / "cast.css"
    if scss_src.is_dir() and css_built.is_file():
        pairs.append((scss_src, css_built))

    # cast-vue pattern
    vue_src = repo_root / "cast_vue" / "static" / "src"
    vue_manifest = repo_root / "cast_vue" / "static" / "cast_vue" / "manifest.json"
    if vue_src.is_dir() and vue_manifest.is_file():
        pairs.append((vue_src, vue_manifest))

    return pairs


def main() -> None:
    parser = argparse.ArgumentParser(description="Check asset build freshness")
    parser.add_argument(
        "--source-dir",
        action="append",
        dest="source_dirs",
        help="Source directory to check (can be repeated)",
    )
    parser.add_argument(
        "--manifest",
        action="append",
        dest="manifests",
        help="Manifest or built file to compare against (paired with --source-dir)",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root for auto-detection (default: cwd)",
    )

    args = parser.parse_args()

    # Build pairs from explicit args or auto-detect
    if args.source_dirs and args.manifests:
        if len(args.source_dirs) != len(args.manifests):
            print("Error: --source-dir and --manifest must be provided in equal numbers")
            sys.exit(2)
        pairs = [(Path(s), Path(m)) for s, m in zip(args.source_dirs, args.manifests)]
    else:
        pairs = detect_pairs(args.repo_root)

    if not pairs:
        print("No source/manifest pairs found. Use --source-dir and --manifest, or run from a repo root.")
        sys.exit(2)

    all_fresh = True
    for source_dir, manifest in pairs:
        is_fresh, message = check_freshness(source_dir, manifest)
        print(message)
        if not is_fresh:
            all_fresh = False

    sys.exit(0 if all_fresh else 1)


if __name__ == "__main__":
    main()
