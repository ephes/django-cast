"""Shared test data and setup helpers."""

from bs4 import BeautifulSoup


def assert_safe_fragment(html):
    soup = BeautifulSoup(html, "html.parser")
    assert not soup.find(["script", "img", "svg", "math", "iframe", "style", "object", "embed"])
    for tag in soup.find_all(True):
        assert not any(name.startswith("on") or name in {"style", "srcdoc", "target"} for name in tag.attrs)
        href = tag.get("href", "")
        assert not any(scheme in href.lower() for scheme in ("javascript:", "vbscript:", "data:"))
