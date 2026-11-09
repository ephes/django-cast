import io
import json
from argparse import Namespace
from http.client import BadStatusLine, IncompleteRead
from pathlib import Path
from unittest.mock import MagicMock
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

import pytest

# scripts/playwright_utils.py is a dev-only helper that exits when playwright is
# missing. The tox dependency-compatibility environments install only the
# package's test dependencies, so skip this module there; the uv dev-group jobs
# install playwright and still run it.
pytest.importorskip("playwright", reason="playwright is a dev-group dependency, not a tox test dependency")

from scripts import playwright_utils as browser_tools  # noqa: E402


@pytest.fixture
def browser_env(tmp_path, monkeypatch):
    browser = MagicMock()
    context = browser.new_context.return_value
    page = context.new_page.return_value
    page.goto.return_value.status = 200
    page.goto.return_value.url = "http://synthetic.test/final/"
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
    healthy_context.new_page.return_value.goto.return_value = Namespace(status=200, url="http://synthetic.test/final/")
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


@pytest.mark.parametrize("status,exit_code", [(200, 0), (204, 0), (404, 1), (500, 1), (302, 1), (None, 1)])
def test_http_verdict(browser_env, status, exit_code, capsys):
    _, context, page, args = browser_env
    page.goto.return_value = None if status is None else Namespace(status=status, url="http://synthetic.test/final/")
    with pytest.raises(SystemExit) as error:
        browser_tools.cmd_check_page(args)
    assert error.value.code == exit_code
    assert ("HTTP" in capsys.readouterr().out) == bool(exit_code)
    context.close.assert_called_once()


@pytest.mark.parametrize("status", [200, 404, 500, None])
def test_screenshot_records_final_response(browser_env, tmp_path, status):
    browser, _, page, _ = browser_env
    final_url = "http://synthetic.test/final/" if status is not None else None
    page.goto.return_value = None if status is None else Namespace(status=status, url=final_url)
    result = browser_tools.take_screenshot(browser, "http://synthetic.test/redirect/", "plain", "desktop", tmp_path)
    meta = json.loads(Path(result.meta_path).read_text())
    assert meta["http_status"] == result.http_status == status
    assert meta["response_url"] == result.response_url == final_url


def test_final_redirect_success(browser_env):
    _, _, page, args = browser_env
    page.goto.return_value = Namespace(status=200, url="http://synthetic.test/final/")
    with pytest.raises(SystemExit) as error:
        browser_tools.cmd_check_page(args)
    assert error.value.code == 0


@pytest.mark.parametrize("status", [404, None])
def test_comparison_escapes_every_dynamic_field(browser_env, tmp_path, monkeypatch, status):
    from bs4 import BeautifulSoup

    hostile = "</code><script>alert('x')</script><img src=x onerror=bad>&\\\""
    image = tmp_path / "image.png"
    image.write_bytes(b"synthetic png")
    result = browser_tools.PageResult(
        theme=hostile,
        viewport="desktop",
        url=hostile,
        http_status=status,
        response_url=hostile,
        console_errors=[hostile],
        failed_requests=[hostile],
        screenshot_path=str(image),
    )
    _, _, _, args = browser_env
    args.path = hostile
    args.all_viewports = True
    monkeypatch.setattr(browser_tools, "VIEWPORTS", {"desktop": {"width": 1280, "height": 720}})
    monkeypatch.setattr(browser_tools, "discover_themes", lambda _: ["plain"])
    monkeypatch.setattr(browser_tools, "take_screenshot", lambda *a, **kw: result)
    browser_tools.cmd_compare_page(args)
    report = (tmp_path / "compare.html").read_text()
    soup = BeautifulSoup(report, "html.parser")
    assert not soup.find_all("script")
    assert len(soup.find_all("img")) == 1
    assert soup.img["src"].startswith("data:image/png;base64,")
    assert soup.img["alt"] == hostile + " desktop"
    assert soup.title.get_text() == "Theme Comparison: " + hostile
    assert soup.h1.code.get_text() == hostile
    assert soup.select_one(".card-header").get_text() == hostile
    assert hostile in soup.select_one(".card-meta").get_text()
    assert soup.get_text().count(hostile) >= 7
    assert f"HTTP {status if status is not None else 'no response'}" in soup.select_one(".card-meta").get_text()
    assert all(not key.startswith("on") for tag in soup.find_all() for key in tag.attrs)


def test_successful_http_still_reports_browser_diagnostics(browser_env, capsys):
    _, _, page, args = browser_env
    callbacks = {}
    page.on.side_effect = lambda event, callback: callbacks.setdefault(event, callback)

    def navigate(*args, **kwargs):
        callbacks["console"](Namespace(type="log", text="ignored"))
        callbacks["console"](Namespace(type="error", text="synthetic console"))
        callbacks["pageerror"](RuntimeError("synthetic page error"))
        callbacks["requestfailed"](Namespace(method="GET", url="http://synthetic.test/asset", failure="failed"))
        return Namespace(status=200, url="http://synthetic.test/final/")

    page.goto.side_effect = navigate
    with pytest.raises(SystemExit) as error:
        browser_tools.cmd_check_page(args)
    assert error.value.code == 1
    text = capsys.readouterr().out
    assert "synthetic console" in text and "synthetic page error" in text and "asset: failed" in text
    assert "ignored" not in text


@pytest.mark.parametrize("status", [404, None])
def test_screenshot_summary_shows_http_failure(browser_env, capsys, status):
    _, _, page, args = browser_env
    page.goto.return_value = None if status is None else Namespace(status=status, url="http://synthetic.test/final/")
    browser_tools.cmd_screenshot_all(args)
    text = capsys.readouterr().out
    label = f"HTTP {status}" if status is not None else "no HTTP response"
    assert f"plain/desktop: {label}" in text
    assert f"bootstrap5/desktop: {label}" in text
