#!/usr/bin/env python3
"""Show shipped django-cast frontend bundle sizes."""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from rich import box
    from rich.console import Console
    from rich.table import Table
except ImportError:  # pragma: no cover - rich is provided by the just recipe
    Console = None  # type: ignore[assignment, misc]

FRIENDLY_NAMES = {
    "src/audio/custom-player.ts": "Custom player",
    "src/audio/podlove-player.ts": "Podlove player",
    "src/gallery/image-gallery-bs4.ts": "Image gallery",
    "src/comments/ajaxcomments.ts": "Ajax comments",
}

KIND_STYLES = {"js": "yellow", "css": "magenta"}


@dataclass(frozen=True)
class Bundle:
    """A shipped static asset to include in the size report."""

    label: str
    kind: str
    path: Path


@dataclass(frozen=True)
class MeasuredBundle:
    """A bundle plus its measured raw and compressed sizes."""

    label: str
    kind: str
    path: Path
    raw_bytes: int | None
    gzip_bytes: int | None


def format_kib(size: int | None) -> str:
    """Format a byte count as KiB for the report table."""
    if size is None:
        return "missing"
    return f"{size / 1024:,.1f}"


def gzip_size(path: Path) -> int:
    """Return the gzip-compressed size for a file's current bytes."""
    return len(gzip.compress(path.read_bytes(), compresslevel=9, mtime=0))


def measure(bundle: Bundle) -> MeasuredBundle:
    """Measure a bundle, preserving missing files as reportable rows."""
    if not bundle.path.is_file():
        return MeasuredBundle(bundle.label, bundle.kind, bundle.path, None, None)
    return MeasuredBundle(bundle.label, bundle.kind, bundle.path, bundle.path.stat().st_size, gzip_size(bundle.path))


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    """Load the Vite manifest or fail with a clear error."""
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Vite manifest not found: {manifest_path}")
    with manifest_path.open() as manifest_file:
        data = json.load(manifest_file)
    if not isinstance(data, dict):
        raise ValueError(f"Vite manifest must be a JSON object: {manifest_path}")
    return data


def vite_bundles(repo_root: Path) -> list[Bundle]:
    """Return Vite entry JS bundles plus CSS sidecars from the shipped manifest."""
    vite_dir = repo_root / "src" / "cast" / "static" / "cast" / "vite"
    manifest = load_manifest(vite_dir / "manifest.json")
    bundles: list[Bundle] = []

    for source, entry in sorted(manifest.items()):
        if not isinstance(entry, dict) or not entry.get("isEntry"):
            continue

        file_name = entry.get("file")
        if isinstance(file_name, str):
            bundles.append(Bundle(source, "js", vite_dir / file_name))

        css_files = entry.get("css", [])
        if isinstance(css_files, list):
            for css_file in css_files:
                if isinstance(css_file, str):
                    bundles.append(Bundle(source, "css", vite_dir / css_file))

    return bundles


def comments_bundles(repo_root: Path) -> list[Bundle]:
    """Return non-Vite JS that is built by the comments Vite config."""
    return [
        Bundle(
            "src/comments/ajaxcomments.ts",
            "js",
            repo_root / "src" / "cast" / "static" / "fluent_comments" / "js" / "ajaxcomments.js",
        )
    ]


def static_js_bundles(repo_root: Path, known_paths: set[Path]) -> list[Bundle]:
    """Return additional shipped static JS files that are not built by the main recipes."""
    static_root = repo_root / "src" / "cast" / "static"
    bundles: list[Bundle] = []
    for path in sorted(static_root.rglob("*.js")):
        if path in known_paths:
            continue
        if "/vite/" in path.as_posix():
            continue
        label = path.relative_to(static_root).as_posix()
        bundles.append(Bundle(label, "js", path))
    return bundles


def friendly_name(label: str) -> str:
    """Derive a short human-friendly entry name from a source label."""
    if label in FRIENDLY_NAMES:
        return FRIENDLY_NAMES[label]
    stem = Path(label).stem
    return stem.replace("-", " ").replace("_", " ").capitalize()


def gzip_bar(gzip_bytes: int | None, max_gzip_bytes: int, width: int = 12) -> str:
    """Render a proportional bar comparing gzip sizes within one table."""
    if gzip_bytes is None or max_gzip_bytes <= 0:
        return ""
    return "█" * max(1, round(width * gzip_bytes / max_gzip_bytes))


def totals(bundles: list[MeasuredBundle], *, kind: str | None = None) -> tuple[int, int]:
    """Return summed raw and gzip bytes for measured bundles of one kind."""
    measured = [
        bundle
        for bundle in bundles
        if (kind is None or bundle.kind == kind) and bundle.raw_bytes is not None and bundle.gzip_bytes is not None
    ]
    raw_total = sum(bundle.raw_bytes or 0 for bundle in measured)
    gzip_total = sum(bundle.gzip_bytes or 0 for bundle in measured)
    return raw_total, gzip_total


class PlainRenderer:
    """Render the report as plain aligned text (no color, no dependencies)."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    def table(self, title: str, bundles: list[MeasuredBundle]) -> None:
        print(title)
        if not bundles:
            print("  none")
            print()
            return

        rows = [
            (
                bundle.label,
                bundle.kind,
                bundle.path.relative_to(self.repo_root).as_posix(),
                format_kib(bundle.raw_bytes),
                format_kib(bundle.gzip_bytes),
            )
            for bundle in bundles
        ]
        headers = ("source", "kind", "file", "raw KiB", "gzip KiB")
        widths = [max(len(row[index]) for row in (*rows, headers)) for index in range(len(headers))]
        header = "  " + "  ".join(value.ljust(widths[index]) for index, value in enumerate(headers))
        print(header)
        print("  " + "  ".join("-" * width for width in widths))
        for row in rows:
            print("  " + "  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))
        print()

    def summary(self, title: str, bundles: list[MeasuredBundle], *, kind: str | None = None) -> None:
        raw_total, gzip_total = totals(bundles, kind=kind)
        print(f"{title}: {format_kib(raw_total)} KiB raw / {format_kib(gzip_total)} KiB gzip")

    def blank(self) -> None:
        print()

    def note(self, text: str) -> None:
        print(text)


class RichRenderer:
    """Render the report as colored rich tables (matches the `just loc` style)."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.console = Console()

    def display_path(self, path: Path) -> str:
        static_root = self.repo_root / "src" / "cast" / "static"
        try:
            return path.relative_to(static_root).as_posix()
        except ValueError:
            return path.relative_to(self.repo_root).as_posix()

    def table(self, title: str, bundles: list[MeasuredBundle]) -> None:
        if not bundles:
            self.console.print(f"[bold]{title}[/]")
            self.console.print("  none")
            self.console.print()
            return

        table = Table(title=title, title_justify="left", title_style="bold", box=box.SIMPLE_HEAD)
        table.add_column("entry", style="bold cyan", no_wrap=True)
        table.add_column("kind", no_wrap=True)
        table.add_column("raw KiB", justify="right")
        table.add_column("gzip KiB", justify="right", style="bold")
        table.add_column("", style="cyan", no_wrap=True)
        table.add_column("file", style="dim", overflow="fold")

        max_gzip = max((bundle.gzip_bytes or 0) for bundle in bundles)
        for bundle in bundles:
            missing = bundle.raw_bytes is None
            table.add_row(
                friendly_name(bundle.label),
                f"[{KIND_STYLES.get(bundle.kind, 'white')}]{bundle.kind}[/]",
                "[red]missing[/]" if missing else format_kib(bundle.raw_bytes),
                "[red]missing[/]" if missing else format_kib(bundle.gzip_bytes),
                gzip_bar(bundle.gzip_bytes, max_gzip),
                self.display_path(bundle.path),
            )
        self.console.print(table)
        self.console.print()

    def summary(self, title: str, bundles: list[MeasuredBundle], *, kind: str | None = None) -> None:
        raw_total, gzip_total = totals(bundles, kind=kind)
        self.console.print(
            f"[bold]{title}:[/] {format_kib(raw_total)} KiB raw / [bold cyan]{format_kib(gzip_total)}[/] KiB gzip"
        )

    def blank(self) -> None:
        self.console.print()

    def note(self, text: str) -> None:
        self.console.print(f"[dim]{text}[/]")


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Show shipped django-cast frontend bundle sizes")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root (default: current working directory)",
    )
    parser.add_argument(
        "--include-static-js",
        action="store_true",
        help="Also list additional static JS files that are shipped but not built by js-build-all",
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        help="Force plain text output (no rich tables/colors)",
    )
    return parser.parse_args()


def main() -> None:
    """Print the bundle-size report."""
    args = parse_args()
    repo_root = args.repo_root.resolve()

    try:
        vite = [measure(bundle) for bundle in vite_bundles(repo_root)]
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)

    comments = [measure(bundle) for bundle in comments_bundles(repo_root)]
    built = [*vite, *comments]

    renderer: PlainRenderer | RichRenderer
    if args.plain or Console is None:
        renderer = PlainRenderer(repo_root)
    else:
        renderer = RichRenderer(repo_root)

    renderer.table("Vite entry bundles shipped from src/cast/static/cast/vite/", vite)
    renderer.table("Other built JS shipped by django-cast", comments)
    renderer.summary("Vite entry JS total", vite, kind="js")
    renderer.summary("Vite CSS sidecar total", vite, kind="css")
    renderer.summary("Built JS total", [*vite, *comments], kind="js")

    if args.include_static_js:
        known_paths = {bundle.path for bundle in built}
        static_js = [measure(bundle) for bundle in static_js_bundles(repo_root, known_paths)]
        renderer.blank()
        renderer.table("Additional shipped static JS (not built by js-build-all)", static_js)
        renderer.summary("Additional static JS total", static_js, kind="js")

    renderer.blank()
    renderer.note(
        "Note: gzip KiB is a local compression estimate; actual transfer depends on server/CDN settings and cache."
    )
    renderer.note("Page load depends on the template and settings, so add only the entries that page includes.")


if __name__ == "__main__":
    main()
