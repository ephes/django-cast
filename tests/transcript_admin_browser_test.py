"""Opt-in Wagtail journey: CAST_RUN_BROWSER=1 uv run pytest tests/transcript_admin_browser_test.py."""

import json
import os

import pytest
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from cast.models import Contributor, EpisodeContributor
from tests.known_speaker_apply_test import make_transcript


class BrowserVoxhelmClient:
    diarization_enabled = True
    known_speaker_enabled = False

    def submit_transcription_job(self, **kwargs):
        return {"id": "browser-job", "state": "queued"}

    def wait_for_job(self, job_id):
        return {
            "id": job_id,
            "state": "succeeded",
            "result": {"artifacts": {name: name for name in ("podlove", "dote", "vtt", "speakers")}},
        }

    def download_artifact(self, name):
        if name == "vtt":
            return b"WEBVTT\n\n00:00:00.000 --> 00:00:03.000\n<v Speaker 1>Regenerated</v>\n"
        data = {
            "podlove": {"transcripts": [{"speaker": "Speaker 1", "start_ms": 0, "text": "Regenerated"}]},
            "dote": {
                "lines": [
                    {
                        "speakerDesignation": "Speaker 1",
                        "startTime": "00:00:00,000",
                        "endTime": "00:00:03,000",
                        "text": "Regenerated",
                    }
                ]
            },
            "speakers": {"segments": [{"start": 0, "speaker_uncertain": True}]},
        }
        return json.dumps(data[name]).encode()


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(os.environ.get("CAST_RUN_BROWSER") != "1", reason="Opt-in real Chromium journey")
def test_transcript_admin_journey(client, pg_editor_actors, request, settings, live_server, monkeypatch):
    admin_user, _ = pg_editor_actors
    episode = request.getfixturevalue("episode")
    monkeypatch.setenv("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    settings.SESSION_ENGINE = "django.contrib.sessions.backends.db"
    client.force_login(admin_user)
    settings.CAST_VOXHELM_API_BASE = "https://voxhelm.example"
    settings.CAST_VOXHELM_API_KEY = "test"
    monkeypatch.setattr("cast.voxhelm.service.VoxhelmClient.from_settings", lambda **kwargs: BrowserVoxhelmClient())
    monkeypatch.setattr(
        "cast.voxhelm.service.resolve_audio_source_url", lambda audio: "https://media.example/audio.m4a"
    )
    host = Contributor.objects.create(display_name="Host", slug="host")
    EpisodeContributor.objects.create(episode=episode, contributor=host, role="host")
    episode.save_revision()
    transcript = make_transcript(
        episode.podcast_audio,
        podlove={
            "transcripts": [
                {"speaker": "Speaker 1", "start_ms": index * 3000, "text": "Hello"} for index in range(1200)
            ]
        },
        speakers={"segments": [{"start": index * 3.0, "speaker_uncertain": True} for index in range(1200)]},
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
            page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
            page.goto(live_server.url + reverse("cast-voxhelm:generate_episode", args=(episode.pk,)))
            expect(page.get_by_role("button", name="Replace and generate transcript")).to_be_visible()
            page.get_by_role("link", name="Cancel", exact=True).click()
            expect(page).to_have_url(live_server.url + reverse("wagtailadmin_pages:edit", args=(episode.pk,)))
            expect(page.get_by_role("link", name="Edit transcript and speakers")).to_be_visible()
            page.goto(live_server.url + reverse("cast-transcript:add") + f"?audio={episode.podcast_audio_id}")
            expect(page.locator("#id_audio")).to_have_value(str(episode.podcast_audio_id))
            page.goto(live_server.url + reverse("cast-transcript:edit", args=(transcript.pk,)))
            expect(page.get_by_role("heading", name=f"Transcript: {episode.title}")).to_be_visible()
            page.get_by_text("Files", exact=True).click()
            page.get_by_role("button", name="Save", exact=True).click()
            expect(page).to_have_url(live_server.url + reverse("cast-transcript:edit", args=(transcript.pk,)))
            expect(page.get_by_role("button", name="Save speaker mappings")).to_be_visible()
            expect(page.locator(".cast-known-speaker-segments tbody tr")).to_have_count(50)
            page.get_by_role("button", name="Save segment decisions", exact=True).click()
            expect(page.locator(".cast-known-speaker-segments tbody tr")).to_have_count(50)
            page.get_by_role("link", name="Next", exact=True).click()
            expect(page.locator("select[name=known_speaker_segment_50]")).to_be_visible()
            page.locator("#id_speaker_0").select_option(label="Host (Host)")
            page.get_by_role("button", name="Save speaker mappings", exact=True).click()
            page.get_by_role("link", name="Preview", exact=True).click()
            expect(page.locator(".transcript-passage")).to_have_count(200)
            passage = page.locator(".transcript-passage").first
            passage.locator("[data-edit-text]").click()
            passage.locator("textarea").fill("Cancelled correction")
            passage.locator("textarea").press("Escape")
            expect(passage.locator("[data-edit-text]")).to_have_text("Hello")
            passage.locator("[data-edit-text]").click()
            passage.locator("textarea").fill("Manual browser correction")
            page.route(
                "**/transcript/preview/**",
                lambda route: (
                    route.fulfill(status=503, body="Please try saving again.")
                    if route.request.method == "POST"
                    else route.continue_()
                ),
            )
            passage.locator("textarea").press("Enter")
            expect(passage.locator(".passage-save-status")).to_have_text("Please try saving again.")
            expect(passage.locator("textarea")).to_be_visible()
            page.unroute("**/transcript/preview/**")
            passage.locator("textarea").press("Meta+Enter")
            expect(passage.locator(".passage-save-status")).to_have_text("Saved")
            expect(passage.locator("[data-edit-text]")).to_have_text("Manual browser correction")
            passage.get_by_text("Change speaker", exact=True).click()
            passage.locator("select[name=speaker]").select_option("")
            passage.get_by_role("button", name="Save speaker", exact=True).click()
            expect(page.get_by_text("1 passages without a name", exact=True)).to_be_visible()
            page.goto(live_server.url + reverse("wagtailadmin_pages:edit", args=(episode.pk,)))
            expect(page.get_by_text("1 of 1 voices named")).to_be_visible()
            page.get_by_role("link", name="Generate again…", exact=True).click()
            page.get_by_role("button", name="Replace and generate transcript", exact=True).click()
            page.get_by_role("link", name="Name the voices", exact=True).click()
            expect(page.locator("#id_speaker_0")).to_have_value("")
            expect(page.get_by_text("Before the transcript changed: Host.", exact=False)).to_be_visible()
            page.get_by_role("button", name="Save speaker mappings", exact=True).click()
            expect(page.locator("#id_speaker_0")).to_have_value("")
            page.get_by_role("button", name="Restore the version from", exact=False).click()
            page.get_by_role("link", name="Preview", exact=True).click()
            expect(page.locator("[data-edit-text]").first).to_have_text("Manual browser correction")
            assert [error for error in errors if "503" not in error] == []
        finally:
            browser.close()


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(os.environ.get("CAST_RUN_BROWSER") != "1", reason="Opt-in real Chromium journey")
def test_upload_and_contributor_defaults_in_browser(
    client, pg_editor_actors, request, settings, live_server, monkeypatch
):
    admin_user, _ = pg_editor_actors
    episode = request.getfixturevalue("episode")
    monkeypatch.setenv("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    settings.SESSION_ENGINE = "django.contrib.sessions.backends.db"
    client.force_login(admin_user)
    host = Contributor.objects.create(display_name="Previous Host", slug="previous-host")
    EpisodeContributor.objects.create(episode=episode, contributor=host, role="host")
    episode.save_revision()
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
            page.goto(live_server.url + reverse("wagtailsnippets_cast_contributor:add"))
            page.locator("#id_display_name").fill("New Guest")
            page.locator("#id_display_name").press("Tab")
            expect(page.locator("#id_slug")).to_have_value("new-guest")
            page.goto(
                live_server.url + reverse("wagtailadmin_pages:add", args=("cast", "episode", episode.get_parent().pk))
            )
            expect(page.locator("[name='contributor_assignments-0-contributor']")).to_have_value(str(host.pk))
            page.goto(live_server.url + reverse("cast-transcript:add") + f"?audio={episode.podcast_audio_id}")
            page.get_by_role("button", name="Upload", exact=True).click()
            expect(page.get_by_text("Upload at least one transcript file.", exact=True)).to_be_visible()
            page.locator("#id_podlove").set_input_files(
                {"name": "wrong.vtt", "mimeType": "text/vtt", "buffer": b"WEBVTT\n"}
            )
            page.get_by_role("button", name="Upload", exact=True).click()
            expect(
                page.get_by_text("This is a WebVTT file. Upload it in the WebVTT Transcript field.", exact=True)
            ).to_be_visible()
            page.locator("#id_vtt").set_input_files(
                {
                    "name": "correct.vtt",
                    "mimeType": "text/vtt",
                    "buffer": b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nUploaded\n",
                }
            )
            page.get_by_role("button", name="Upload", exact=True).click()
            expect(page.get_by_text("No transcript yet for: web player.", exact=True)).to_be_visible()
            page.get_by_role("link", name="Preview", exact=True).click()
            expect(page.locator("[data-edit-text]")).to_have_text("Uploaded")
        finally:
            browser.close()
