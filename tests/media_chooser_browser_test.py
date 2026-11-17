"""Opt-in: CAST_RUN_BROWSER=1 uv run pytest tests/media_chooser_browser_test.py -v."""

import os
import re

import pytest
from django.urls import reverse

from cast.models import Post
from cast.views.media import reindex

playwright_api = pytest.importorskip("playwright.sync_api", reason="Playwright is an optional dev-only dependency")
expect = playwright_api.expect
sync_playwright = playwright_api.sync_playwright


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(os.environ.get("CAST_RUN_BROWSER") != "1", reason="Opt-in real Chromium journey")
@pytest.mark.parametrize("media_type", ["audio", "video"])
def test_media_chooser_streamfield_journey(
    media_type, client, pg_editor_actors, request, settings, live_server, monkeypatch
):
    admin_user, _ = pg_editor_actors
    post = request.getfixturevalue("post")
    media = request.getfixturevalue(media_type)
    media.title = "Synthetic chooser medium"
    media.save(update_fields=["title"])
    reindex(media)
    # Exercise a supported optional chooser so a cleared block can be saved.
    block = Post._meta.get_field("body").stream_block.child_blocks["overview"].child_blocks[media_type]
    monkeypatch.setattr(block.field, "required", False)
    monkeypatch.setattr(block.widget, "is_required", False)
    monkeypatch.setattr(block.field.widget, "is_required", False)
    post.body = [{"type": "overview", "value": [{"type": media_type, "value": None}]}]
    post.save()
    post.save_revision()
    monkeypatch.setenv("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    settings.SESSION_ENGINE = "django.contrib.sessions.backends.db"
    client.force_login(admin_user)
    edit_path = reverse("wagtailadmin_pages:edit", args=(post.pk,))
    # Prove the synthetic editor/search setup even when browser launch is blocked.
    assert client.get(edit_path).status_code == 200
    search = client.get(reverse(f"cast{media_type}:chooser"), {"q": "Synthetic"})
    assert search.status_code == 200
    assert media.title.encode() in search.content
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
            page.goto(live_server.url + edit_path)
            widgets = page.locator(f".{media_type}-chooser")
            expect(widgets).to_have_count(1)
            # An enclosing editor listener must see native bubbling changes.
            page.evaluate("""() => {
                window.mediaChanges = [];
                document.querySelector('#page-edit-form').addEventListener('change', event => {
                    if (event.target.type === 'hidden') window.mediaChanges.push(event.target.value);
                });
                const sentinel = document.createElement('input');
                sentinel.id = 'id_q'; sentinel.value = 'editor sentinel';
                document.body.prepend(sentinel);
            }""")
            widgets.first.locator("[data-chooser-action-choose], .action-choose").last.click()
            modal = page.locator(".modal-body")
            expect(modal.locator("form.media-search")).to_be_visible()
            with page.expect_response(lambda response: "q=Synthetic" in response.url and response.status == 200):
                modal.locator("#id_q").fill("Synthetic")
            expect(page.locator("body > #id_q")).to_have_value("editor sentinel")
            choice = modal.locator("a.media-choice").filter(has_text=media.title).first
            expect(choice).to_be_visible()
            choice.click()
            expect(widgets.first.locator(".title")).to_have_text(media.title)
            expect(page.locator(".modal-body")).to_have_count(0)
            assert page.evaluate("window.mediaChanges") == [str(media.pk)]
            # Open and retire a second chooser with a debounce pending.
            widgets.first.locator("[data-chooser-action-choose], .action-choose").first.evaluate("el => el.click()")
            expect(modal.locator("#id_q")).to_be_visible()
            modal.locator("#id_q").fill("retired search")
            page.locator(".modal [data-dismiss=modal]").click()
            expect(page.locator(".modal-body")).to_have_count(0)
            # Wagtail moves dropdown actions into a popup that exists only while open.
            widgets.first.locator('[data-w-dropdown-target="toggle"]').click()
            page.locator(".tippy-box [data-chooser-action-clear]:visible").click()
            expect(widgets.first).to_have_class(re.compile(r"\bblank\b"))
            expect(widgets.first.locator(".title")).to_have_text("")
            expect(widgets.first.locator("[data-chooser-edit-link]")).not_to_have_attribute("href")
            assert page.evaluate("window.mediaChanges") == [str(media.pk), ""]
            child = widgets.first.locator("xpath=ancestor::*[@data-streamfield-child][1]")
            child.locator('[data-streamfield-action="DUPLICATE"]').evaluate("el => el.click()")
            expect(widgets).to_have_count(2)
            duplicated = widgets.nth(1).locator("xpath=ancestor::*[@data-streamfield-child][1]")
            duplicated.locator('[data-streamfield-action="MOVE_UP"]').evaluate("el => el.click()")
            # Duplication hydrates silently and must not resurrect the chosen ID.
            for widget in widgets.all():
                expect(widget).to_have_class(re.compile(r"\bblank\b"))
            assert page.evaluate("window.mediaChanges") == [str(media.pk), ""]
            with page.expect_response(
                lambda response: response.request.method == "POST" and edit_path in response.url
            ):
                page.get_by_role("button", name="Save draft", exact=True).click()
            page.goto(live_server.url + edit_path)
            expect(widgets).to_have_count(2)
            for widget in widgets.all():
                expect(widget).to_have_class(re.compile(r"\bblank\b"))
            post.refresh_from_db()
            saved = post.get_latest_revision_as_object().body[0].value
            assert [item.value for item in saved] == [None, None]
            assert errors == []
        finally:
            browser.close()
