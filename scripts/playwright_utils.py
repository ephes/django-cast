#!/usr/bin/env python3
"""
Playwright utilities for django-cast theme development.

Screenshot, check, and compare pages across themes and viewports.
Uses the plain playwright sync API (not pytest-playwright).

Usage:
    python scripts/playwright_utils.py screenshot /styleguide-blog/ --theme bootstrap5
    python scripts/playwright_utils.py screenshot-all /styleguide-blog/
    python scripts/playwright_utils.py check-page /styleguide-blog/ --theme bootstrap5
    python scripts/playwright_utils.py compare-page /styleguide-blog/

Output goes to /tmp/cast-screenshots/ by default.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, Page, Browser
except ImportError:
    print("playwright is not installed. Install it with: uv add --dev playwright && playwright install chromium")
    sys.exit(1)

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_OUTPUT_DIR = "/tmp/cast-screenshots"

VIEWPORTS = {
    "desktop": {"width": 1280, "height": 720},
    "tablet": {"width": 768, "height": 1024},
    "mobile": {"width": 390, "height": 844},
}

# Themes to screenshot — dynamically discovered via dev-health endpoint.
# Fallback if the endpoint is unavailable.
FALLBACK_THEMES = ["bootstrap5", "bootstrap4", "plain"]


@dataclass
class PageResult:
    """Result of visiting a page."""

    theme: str
    viewport: str
    url: str
    console_errors: list[str] = field(default_factory=list)
    failed_requests: list[str] = field(default_factory=list)
    screenshot_path: str | None = None
    meta_path: str | None = None


def collect_browser_errors(page: Page) -> tuple[list[str], list[str]]:
    """Set up console error and request failure collection on a page."""
    errors: list[str] = []
    failed: list[str] = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.on("requestfailed", lambda req: failed.append(f"{req.method} {req.url}: {req.failure}"))
    return errors, failed


def discover_themes(base_url: str) -> list[str]:
    """Try to discover installed themes via the dev-health endpoint."""
    import urllib.request
    import urllib.error

    try:
        with urllib.request.urlopen(f"{base_url}/cast/dev-health/", timeout=3) as resp:
            data = json.loads(resp.read())
            return [t["slug"] for t in data.get("themes", [])]
    except Exception:
        return FALLBACK_THEMES


def take_screenshot(
    browser: Browser,
    url: str,
    theme: str,
    viewport: str,
    output_dir: Path,
    *,
    full_page: bool = True,
    wait_ms: int = 1000,
) -> PageResult:
    """Take a screenshot of a URL with a specific theme and viewport."""
    vp = VIEWPORTS.get(viewport, VIEWPORTS["desktop"])
    context = browser.new_context(viewport=vp)  # type: ignore[arg-type]
    page = context.new_page()
    errors, failed = collect_browser_errors(page)

    # Append ?theme= to URL
    separator = "&" if "?" in url else "?"
    full_url = f"{url}{separator}theme={theme}"

    page.goto(full_url, wait_until="networkidle")
    time.sleep(wait_ms / 1000)

    # Take screenshot
    filename = f"{theme}-{viewport}.png"
    screenshot_path = output_dir / filename
    page.screenshot(path=str(screenshot_path), full_page=full_page)

    # Write metadata
    meta_filename = f"{theme}-{viewport}.json"
    meta_path = output_dir / meta_filename
    meta = {
        "theme": theme,
        "viewport": viewport,
        "viewport_size": vp,
        "url": full_url,
        "console_errors": list(errors),
        "failed_requests": list(failed),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    meta_path.write_text(json.dumps(meta, indent=2))

    context.close()

    return PageResult(
        theme=theme,
        viewport=viewport,
        url=full_url,
        console_errors=list(errors),
        failed_requests=list(failed),
        screenshot_path=str(screenshot_path),
        meta_path=str(meta_path),
    )


def cmd_screenshot(args: argparse.Namespace) -> None:
    """Take a screenshot of a single page."""
    base_url = args.base_url.rstrip("/")
    url = f"{base_url}{args.path}"
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        result = take_screenshot(browser, url, args.theme, args.viewport, output_dir)
        browser.close()

    print(f"Screenshot: {result.screenshot_path}")
    print(f"Metadata:   {result.meta_path}")
    if result.console_errors:
        print(f"Console errors ({len(result.console_errors)}):")
        for err in result.console_errors:
            print(f"  - {err}")
    if result.failed_requests:
        print(f"Failed requests ({len(result.failed_requests)}):")
        for req in result.failed_requests:
            print(f"  - {req}")


def cmd_screenshot_all(args: argparse.Namespace) -> None:
    """Screenshot all themes at all viewports."""
    base_url = args.base_url.rstrip("/")
    url = f"{base_url}{args.path}"
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    themes = discover_themes(base_url)
    viewports = list(VIEWPORTS.keys()) if args.all_viewports else ["desktop"]

    print(f"Screenshotting {len(themes)} themes × {len(viewports)} viewports...")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        results: list[PageResult] = []
        for theme in themes:
            for viewport in viewports:
                result = take_screenshot(browser, url, theme, viewport, output_dir)
                results.append(result)
                status = "OK" if not result.console_errors else f"{len(result.console_errors)} errors"
                print(f"  {theme}/{viewport}: {status}")
        browser.close()

    # Write summary
    summary_path = output_dir / "summary.json"
    summary = {
        "path": args.path,
        "themes": themes,
        "viewports": viewports,
        "results": [
            {
                "theme": r.theme,
                "viewport": r.viewport,
                "console_errors": len(r.console_errors),
                "failed_requests": len(r.failed_requests),
                "screenshot": r.screenshot_path,
            }
            for r in results
        ],
    }
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"\nSummary: {summary_path}")


def cmd_check_page(args: argparse.Namespace) -> None:
    """Check a page for console errors and failed requests."""
    base_url = args.base_url.rstrip("/")
    url = f"{base_url}{args.path}"
    separator = "&" if "?" in url else "?"
    full_url = f"{url}{separator}theme={args.theme}"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        vp = VIEWPORTS.get(args.viewport, VIEWPORTS["desktop"])
        context = browser.new_context(viewport=vp)  # type: ignore[arg-type]
        page = context.new_page()
        errors, failed = collect_browser_errors(page)

        page.goto(full_url, wait_until="networkidle")
        time.sleep(1)

        context.close()
        browser.close()

    has_issues = bool(errors or failed)
    if errors:
        print(f"Console errors ({len(errors)}):")
        for err in errors:
            print(f"  - {err}")
    if failed:
        print(f"Failed requests ({len(failed)}):")
        for req in failed:
            print(f"  - {req}")
    if not has_issues:
        print(f"No issues found on {full_url}")

    sys.exit(1 if has_issues else 0)


def cmd_compare_page(args: argparse.Namespace) -> None:
    """Generate an HTML comparison report with all screenshots inline."""
    base_url = args.base_url.rstrip("/")
    url = f"{base_url}{args.path}"
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    themes = discover_themes(base_url)
    viewports = list(VIEWPORTS.keys()) if args.all_viewports else ["desktop", "mobile"]

    print(f"Generating comparison: {len(themes)} themes × {len(viewports)} viewports...")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        results: list[PageResult] = []
        for theme in themes:
            for viewport in viewports:
                result = take_screenshot(browser, url, theme, viewport, output_dir)
                results.append(result)
                print(f"  {theme}/{viewport}: captured")
        browser.close()

    # Build HTML report with inline base64 images
    html_parts = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8'>",
        f"<title>Theme Comparison: {args.path}</title>",
        "<style>",
        "body { font-family: system-ui, sans-serif; margin: 1rem; background: #f5f5f5; }",
        "h1 { border-bottom: 2px solid #333; padding-bottom: 0.5rem; }",
        ".grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(350px, 1fr)); gap: 1rem; }",
        ".card { background: #fff; border: 1px solid #ddd; border-radius: 4px; overflow: hidden; }",
        ".card-header { padding: 0.5rem 0.75rem; background: #e8e8e8; font-weight: 600; font-size: 0.875rem; }",
        ".card img { width: 100%; height: auto; display: block; }",
        ".card-meta { padding: 0.5rem 0.75rem; font-size: 0.75rem; color: #666; }",
        ".error { color: #c00; }",
        "</style></head><body>",
        f"<h1>Theme Comparison: <code>{args.path}</code></h1>",
        f"<p>Generated at {time.strftime('%Y-%m-%d %H:%M:%S')}</p>",
    ]

    for viewport in viewports:
        html_parts.append(
            f"<h2>{viewport.title()} ({VIEWPORTS[viewport]['width']}×{VIEWPORTS[viewport]['height']})</h2>"
        )
        html_parts.append("<div class='grid'>")
        for result in results:
            if result.viewport != viewport:
                continue
            img_data = ""
            if result.screenshot_path:
                img_bytes = Path(result.screenshot_path).read_bytes()
                img_data = base64.b64encode(img_bytes).decode()
            errors_html = ""
            if result.console_errors:
                errors_html = f"<span class='error'>{len(result.console_errors)} console errors</span>"
            html_parts.append("<div class='card'>")
            html_parts.append(f"<div class='card-header'>{result.theme}</div>")
            if img_data:
                html_parts.append(f"<img src='data:image/png;base64,{img_data}' alt='{result.theme} {viewport}'>")
            html_parts.append(f"<div class='card-meta'>{result.url} {errors_html}</div>")
            html_parts.append("</div>")
        html_parts.append("</div>")

    html_parts.append("</body></html>")

    compare_path = output_dir / "compare.html"
    compare_path.write_text("\n".join(html_parts))
    print(f"\nComparison report: {compare_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Playwright utilities for django-cast theme development")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"Dev server URL (default: {DEFAULT_BASE_URL})")
    parser.add_argument(
        "--output-dir", default=DEFAULT_OUTPUT_DIR, help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})"
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # screenshot
    p_screenshot = subparsers.add_parser("screenshot", help="Take a screenshot of a page")
    p_screenshot.add_argument("path", help="URL path (e.g. /styleguide-blog/)")
    p_screenshot.add_argument("--theme", default="bootstrap5", help="Theme slug (default: bootstrap5)")
    p_screenshot.add_argument("--viewport", default="desktop", choices=list(VIEWPORTS.keys()), help="Viewport preset")
    p_screenshot.set_defaults(func=cmd_screenshot)

    # screenshot-all
    p_all = subparsers.add_parser("screenshot-all", help="Screenshot all themes")
    p_all.add_argument("path", help="URL path (e.g. /styleguide-blog/)")
    p_all.add_argument("--all-viewports", action="store_true", help="Include all viewports (default: desktop only)")
    p_all.set_defaults(func=cmd_screenshot_all)

    # check-page
    p_check = subparsers.add_parser("check-page", help="Check page for console errors")
    p_check.add_argument("path", help="URL path (e.g. /styleguide-blog/)")
    p_check.add_argument("--theme", default="bootstrap5", help="Theme slug")
    p_check.add_argument("--viewport", default="desktop", choices=list(VIEWPORTS.keys()))
    p_check.set_defaults(func=cmd_check_page)

    # compare-page
    p_compare = subparsers.add_parser("compare-page", help="Generate comparison HTML report")
    p_compare.add_argument("path", help="URL path (e.g. /styleguide-blog/)")
    p_compare.add_argument(
        "--all-viewports", action="store_true", help="Include all viewports (default: desktop+mobile)"
    )
    p_compare.set_defaults(func=cmd_compare_page)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
