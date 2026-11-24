"""Opt-in Chromium checks for the shipped native player share dialog."""

import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

playwright_api = pytest.importorskip("playwright.sync_api", reason="Playwright is an optional dev-only dependency")
pytestmark = pytest.mark.skipif(os.environ.get("CAST_RUN_BROWSER") != "1", reason="Opt-in real Chromium journey")


@pytest.fixture
def player_page():
    assets = Path(__file__).resolve().parents[1] / "src/cast/static/cast/vite"
    manifest = json.loads((assets / "manifest.json").read_text())
    script = manifest["src/audio/custom-player.ts"]["file"]
    payload = json.dumps(
        {
            "audioId": 1,
            "title": "Synthetic episode",
            "duration": 70000,
            "permalink": "/episode/",
            "sources": [{"type": "audio/mp4", "src": "/synthetic.m4a"}],
            "chapters": [],
            "transcript": {"cues": []},
        }
    )
    html = f"""<!doctype html>
        <script type="module" src="/static/{script}"></script>
        <script type="application/json" id="payload">{payload}</script>
        <cast-audio-player data-payload="payload"></cast-audio-player>"""

    def serve(route):
        path = urlsplit(route.request.url).path
        if path == "/episode/":
            route.fulfill(body=html, content_type="text/html")
        elif path.startswith("/static/"):
            route.fulfill(path=assets / path.removeprefix("/static/"), content_type="application/javascript")
        else:
            route.abort()

    with playwright_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ.get("CAST_BROWSER_EXECUTABLE"))
        try:
            page = browser.new_page()
            page.route("http://testserver/**", serve)
            yield page
        finally:
            browser.close()


def test_long_share_offset_round_trips(player_page):
    player_page.goto("http://testserver/episode/")
    player_page.locator("audio").evaluate("(audio) => audio.currentTime = 60005")
    player_page.get_by_role("button", name="Share with current time").click()
    dialog = player_page.get_by_role("dialog", name="Share")
    start_time = dialog.get_by_role("textbox", name="Start time (minutes:seconds)")
    playwright_api.expect(start_time).to_have_value("1000:05")
    assert start_time.evaluate("(input) => input.checkValidity()")
    shared_url = dialog.get_by_role("textbox", name="Share URL").input_value()
    assert parse_qs(urlsplit(shared_url).query) == {"t": ["60005"]}

    player_page.goto(shared_url)
    assert player_page.locator("audio").evaluate("(audio) => audio.currentTime") == 60005


@pytest.mark.parametrize("clipboard", ["undefined", "({writeText: () => Promise.reject(new Error('Denied'))})"])
def test_share_copy_selects_url_when_clipboard_cannot_write(player_page, clipboard):
    player_page.add_init_script(f"Object.defineProperty(navigator, 'clipboard', {{value: {clipboard}}})")
    player_page.goto("http://testserver/episode/")
    player_page.get_by_role("button", name="Share with current time").click()
    dialog = player_page.get_by_role("dialog", name="Share")
    dialog.get_by_role("button", name="Copy", exact=True).click()
    url = dialog.get_by_role("textbox", name="Share URL")
    playwright_api.expect(url).to_be_focused()
    assert url.evaluate("(input) => [input.selectionStart, input.selectionEnd]") == [0, len(url.input_value())]
    playwright_api.expect(dialog.get_by_role("button", name="Copy", exact=True)).to_be_visible()
