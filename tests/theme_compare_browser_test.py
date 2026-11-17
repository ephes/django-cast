"""CAST_RUN_BROWSER=1 uv run pytest tests/theme_compare_browser_test.py"""

import os

import pytest
from bs4 import BeautifulSoup
from django.urls import reverse

from tests.theme_compare_helpers import LOCAL_COMPARE_PATHS, UNSAFE_COMPARE_PATHS

playwright_api = pytest.importorskip("playwright.sync_api", reason="Playwright is an optional dev-only dependency")


@pytest.mark.django_db
@pytest.mark.skipif(os.environ.get("CAST_RUN_BROWSER") != "1", reason="Opt-in real Chromium URL resolution")
def test_rendered_comparison_iframes_stay_same_origin(settings, client):
    settings.CAST_ENABLE_DEV_TOOLS = True
    sources = []
    for path in UNSAFE_COMPARE_PATHS + LOCAL_COMPARE_PATHS:
        response = client.get(reverse("cast:theme-compare"), {"path": path})
        assert response.status_code == 200
        frames = BeautifulSoup(response.content, "html.parser").select("iframe")
        assert frames
        sources.extend(frame["src"] for frame in frames)

    with playwright_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ.get("CAST_BROWSER_EXECUTABLE"))
        try:
            page = browser.new_page()
            # URL parsing only: never navigate to a supplied destination.
            resolved = page.evaluate(
                """sources => sources.map(src => new URL(src, 'https://cast.example').origin)""", sources
            )
            assert resolved == ["https://cast.example"] * len(sources)
        finally:
            browser.close()
