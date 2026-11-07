import io
import json
from argparse import Namespace
from http.client import BadStatusLine, IncompleteRead
from pathlib import Path
from unittest.mock import MagicMock
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

import pytest

from scripts import playwright_utils as browser_tools


@pytest.fixture
def browser_env(tmp_path, monkeypatch):
    browser = MagicMock()
    context = browser.new_context.return_value
    page = context.new_page.return_value
    page.goto.return_value.status = 200
    p = MagicMock()
    p.chromium.executable_path = str(tmp_path)
    p.chromium.launch.return_value = browser
    manager = MagicMock()
    manager.__enter__.return_value = p
    monkeypatch.setattr(browser_tools, "sync_playwright", lambda: manager)
    monkeypatch.setattr(browser_tools.time, "sleep", lambda _: None)
    monkeypatch.setattr(browser_tools, "discover_themes", lambda _: ["plain", "bootstrap5"])
    args = Namespace(
        base_url="http://synthetic.test",
        path="/page/",
        output_dir=str(tmp_path),
        theme="plain",
        viewport="desktop",
        all_viewports=False,
    )
    return browser, context, page, args


@pytest.mark.parametrize("boundary", ["new_page", "goto", "screenshot", "metadata"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_screenshot_failure_closes_context(browser_env, tmp_path, monkeypatch, boundary, cleanup_fails):
    browser, context, page, _ = browser_env
    failure = RuntimeError("primary failure")
    if boundary == "metadata":
        monkeypatch.setattr(Path, "write_text", MagicMock(side_effect=failure))
    elif boundary == "new_page":
        context.new_page.side_effect = failure
    else:
        getattr(page, boundary).side_effect = failure
    if cleanup_fails:
        context.close.side_effect = RuntimeError("cleanup failure")
    with pytest.raises(RuntimeError, match="primary failure") as error:
        browser_tools.take_screenshot(browser, "http://synthetic.test/", "plain", "desktop", tmp_path)
    assert error.value is failure
    context.close.assert_called_once()
    if cleanup_fails:
        assert any("cleanup failure" in note for note in failure.__notes__)


@pytest.mark.parametrize("command", ["cmd_screenshot", "cmd_screenshot_all", "cmd_compare_page", "cmd_check_page"])
def test_command_failure_closes_owned_resources(browser_env, command):
    browser, context, page, args = browser_env
    page.goto.side_effect = RuntimeError("navigation failed")
    browser.close.side_effect = RuntimeError("browser cleanup failed")
    with pytest.raises(RuntimeError, match="navigation failed"):
        getattr(browser_tools, command)(args)
    context.close.assert_called_once()
    browser.close.assert_called_once()


def test_new_capture_uses_fresh_context(browser_env, tmp_path):
    browser, failed_context, page, _ = browser_env
    page.goto.side_effect = RuntimeError("failed page")
    with pytest.raises(RuntimeError):
        browser_tools.take_screenshot(browser, "http://synthetic.test/", "plain", "desktop", tmp_path)
    healthy_context = MagicMock()
    browser.new_context.return_value = healthy_context
    result = browser_tools.take_screenshot(browser, "http://synthetic.test/", "plain", "desktop", tmp_path)
    assert result.console_errors == []
    failed_context.close.assert_called_once()
    healthy_context.close.assert_called_once()


@pytest.mark.parametrize("theme", ["../../outside", "/absolute", "theme&extra=bad#fragment", "a?b=c", "C:\\outside"])
def test_theme_output_and_query_are_contained(browser_env, tmp_path, monkeypatch, theme):
    write_text = Path.write_text

    def contained_write(path, *args, **kwargs):
        assert path.parent.resolve() == tmp_path.resolve()
        return write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", contained_write)
    browser, context, page, _ = browser_env
    result = browser_tools.take_screenshot(
        browser, "http://synthetic.test/page/?x=1&theme=old#anchor", theme, "desktop", tmp_path
    )
    query = parse_qs(urlsplit(page.goto.call_args.args[0]).query)
    assert query == {"x": ["1"], "theme": [theme]}
    assert urlsplit(result.url).fragment == "anchor"
    for name in [result.screenshot_path, result.meta_path]:
        assert Path(name).parent.resolve() == tmp_path.resolve()
    assert json.loads(Path(result.meta_path).read_text())["theme"] == theme
    context.close.assert_called_once()


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"themes": None},
        {"themes": [None]},
        {"themes": [{}]},
        {"themes": [{"slug": 3}]},
        {"themes": [{"slug": ""}]},
        {"themes": [{"slug": "a/b"}, {"slug": "a?b"}]},
        {"themes": [{"slug": "Plain"}, {"slug": "plain"}]},
    ],
)
def test_discovery_rejects_invalid_or_colliding_records(tmp_path, monkeypatch, payload):
    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(json.dumps(payload).encode()))
    with pytest.raises(ValueError):
        browser_tools.discover_themes("http://synthetic.test")


def test_discovery_keeps_original_labels(monkeypatch):
    import urllib.request

    payload = {"themes": [{"slug": "../../outside"}, {"slug": "theme&x=1#f"}]}
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(json.dumps(payload).encode()))
    assert browser_tools.discover_themes("http://synthetic.test") == ["../../outside", "theme&x=1#f"]


@pytest.mark.parametrize(
    "failure",
    [URLError("unavailable"), TimeoutError("timeout"), BadStatusLine("not HTTP"), IncompleteRead(b"partial")],
)
def test_discovery_transport_failures_use_fallback(monkeypatch, failure):
    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", MagicMock(side_effect=failure))
    assert browser_tools.discover_themes("http://synthetic.test") == browser_tools.FALLBACK_THEMES
