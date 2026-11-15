"""Opt-in Wagtail journey: CAST_RUN_BROWSER=1 uv run pytest tests/transcript_admin_browser_test.py."""

import os

import pytest
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from cast.devdata import create_transcript


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(os.environ.get("CAST_RUN_BROWSER") != "1", reason="Opt-in real Chromium journey")
def test_transcript_admin_journey(client, admin_user, episode, settings, live_server, monkeypatch):
    monkeypatch.setenv("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    settings.SESSION_ENGINE = "django.contrib.sessions.backends.db"
    client.force_login(admin_user)
    transcript = create_transcript(
        audio=episode.podcast_audio,
        podlove={"transcripts": [{"speaker": "Speaker 1", "start_ms": 0, "text": "Hello"}]},
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ.get("CAST_BROWSER_EXECUTABLE"))
        try:
            context = browser.new_context()
            context.add_cookies(
                [
                    {
                        "name": settings.SESSION_COOKIE_NAME,
                        "value": client.cookies[settings.SESSION_COOKIE_NAME].value,
                        "url": live_server.url,
                    }
                ]
            )
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(live_server.url + reverse("cast-voxhelm:generate_episode", args=(episode.pk,)))
            expect(page.get_by_role("button", name="Replace and generate transcript")).to_be_visible()
            page.get_by_role("link", name="Cancel", exact=True).click()
            expect(page).to_have_url(live_server.url + reverse("wagtailadmin_pages:edit", args=(episode.pk,)))
            expect(page.get_by_role("link", name="Edit transcript and speakers")).to_be_visible()
            page.goto(live_server.url + reverse("cast-transcript:add") + f"?audio={episode.podcast_audio_id}")
            expect(page.locator("#id_audio")).to_have_value(str(episode.podcast_audio_id))
            page.goto(live_server.url + reverse("cast-transcript:edit", args=(transcript.pk,)))
            expect(page.get_by_role("button", name="Save speaker mappings")).to_be_visible()
            assert errors == []
        finally:
            browser.close()
