"""Opt-in local browser journey: CAST_RUN_BROWSER=1 uv run pytest tests/comment_browser_test.py."""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from tests.comment_author_edits_test import seed_ownership


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(os.environ.get("CAST_RUN_BROWSER") != "1", reason="Opt-in real Chromium journey")
def test_two_open_editors_preserve_conflicting_draft(
    client, comment, post, settings, comments_enabled, live_server, monkeypatch
):
    # Playwright's sync API runs an event loop in this thread; the test's own ORM
    # calls (post URL, assertions) are synchronous and safe here.
    monkeypatch.setenv("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    settings.CAST_COMMENTS_ALLOW_AUTHOR_EDITS = True
    settings.CAST_COMMENTS_EDIT_RATE_LIMIT = 0
    settings.SESSION_ENGINE = "django.contrib.sessions.backends.db"
    seed_ownership(client, comment)
    bundle = Path("src/cast/static/fluent_comments/js/ajaxcomments.js").read_text()
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
            pages = [context.new_page(), context.new_page()]
            for page in pages:
                page.goto(live_server.url + post.get_url())
                page.add_script_tag(content=bundle)
                page.locator(f"#c{comment.pk} .comment-edit-link").click()
            first, second = pages
            first.locator(".comment-edit-textarea").fill("First accepted edit")
            second.locator(".comment-edit-textarea").fill("Unsent browser draft")
            first.locator(".comment-edit-save").click()
            expect(first.locator(f"#c{comment.pk} .comment-text")).to_have_text("First accepted edit")
            second.locator(".comment-edit-save").click()
            expect(second.locator(".comment-edit-status")).to_contain_text("First accepted edit")
            expect(second.locator(".comment-edit-textarea")).to_have_value("Unsent browser draft")
            expect(second.locator(".comment-edit-status")).to_contain_text("Review it before saving again")
            comment.refresh_from_db()
            assert comment.comment == "First accepted edit"
        finally:
            browser.close()
