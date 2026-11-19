"""Opt-in: CAST_RUN_BROWSER=1 uv run pytest tests/twitter_player_browser_test.py."""

import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from django.contrib.staticfiles import finders
from django.urls import reverse

playwright_api = pytest.importorskip("playwright.sync_api", reason="Playwright is an optional dev-only dependency")


@pytest.mark.django_db
@pytest.mark.skipif(os.environ.get("CAST_RUN_BROWSER") != "1", reason="Opt-in real Chromium journey")
def test_twitter_player_bootstraps_under_self_only_script_policy(client, episode):
    title = 'Synthetic "show" with a backslash \\ and </script>'
    blog = episode.blog
    blog.title = title
    blog.save()
    path = reverse("cast:twitter-player", kwargs={"blog_slug": blog.slug, "episode_slug": episode.slug})
    response = client.get(path)
    assert response.status_code == 200

    def serve(route):
        path_info = urlsplit(route.request.url).path
        if path_info == path:
            route.fulfill(
                body=response.content,
                content_type="text/html",
                headers={"Content-Security-Policy": "script-src 'self'"},
            )
        elif path_info.endswith("/embed.5.js"):
            # Isolate the card bootstrap from the third-party renderer.
            route.fulfill(
                content_type="application/javascript",
                body="""window.podlovePlayer = (selector, config) => {
                    const root = document.querySelector(selector);
                    const button = document.createElement('button');
                    button.textContent = 'Play';
                    button.title = config.show.title;
                    root.replaceChildren(button);
                };""",
            )
        else:
            asset = finders.find(path_info.removeprefix("/static/"))
            if asset:
                route.fulfill(body=Path(asset).read_bytes(), content_type="application/javascript")
            else:
                route.abort()

    with playwright_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ.get("CAST_BROWSER_EXECUTABLE"))
        try:
            page = browser.new_page()
            page.add_init_script("""window.cspViolations = [];
                document.addEventListener('securitypolicyviolation', event => {
                    window.cspViolations.push(event.violatedDirective);
                });""")
            page.route("**/*", serve)
            page.goto("http://testserver" + path)
            playwright_api.expect(page.get_by_role("button", name="Play")).to_have_attribute("title", title)
            assert page.evaluate("window.cspViolations") == []
        finally:
            browser.close()
