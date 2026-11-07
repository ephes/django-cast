import gzip
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import show_bundle_sizes as sizes

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/show_bundle_sizes.py"


@pytest.fixture
def inventory(tmp_path):
    vite = tmp_path / "src/cast/static/cast/vite"
    vite.mkdir(parents=True)
    manifest = {
        "b.ts": {"isEntry": True, "file": "b.js", "css": ["shared.css", "missing.css"]},
        "a.ts": {"isEntry": True, "file": "a.js", "css": ["./shared.css", "empty.css"]},
        "chunk": {"file": "chunk.js"},
        "ignored": None,
    }
    (vite / "manifest.json").write_text(json.dumps(manifest))
    for name, content in {
        "a.js": b"aaa",
        "b.js": b"bbbb",
        "shared.css": b"synthetic css" * 128,
        "empty.css": b"",
        "chunk.js": b"chunk",
    }.items():
        (vite / name).write_bytes(content)
    comments = tmp_path / "src/cast/static/fluent_comments/js/ajaxcomments.js"
    comments.parent.mkdir(parents=True)
    comments.write_bytes(b"comments")
    extra = tmp_path / "src/cast/static/cast/extra.js"
    extra.write_bytes(b"extra")
    return tmp_path


def test_inventory_and_plain_cli(inventory):
    rows = sizes.vite_bundles(inventory)
    assert [(row.label, row.kind, row.path.name) for row in rows] == [
        ("a.ts", "js", "a.js"),
        ("a.ts", "css", "shared.css"),
        ("a.ts", "css", "empty.css"),
        ("b.ts", "js", "b.js"),
        ("b.ts", "css", "shared.css"),
        ("b.ts", "css", "missing.css"),
    ]
    known = {row.path for row in [*rows, *sizes.comments_bundles(inventory)]}
    assert [row.path.name for row in sizes.static_js_bundles(inventory, known)] == ["extra.js"]
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(inventory), "--plain", "--include-static-js"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    missing_row = next(line for line in result.stdout.splitlines() if "missing.css" in line)
    assert missing_row.split()[-2:] == ["missing", "missing"]
    assert result.stdout.count("ajaxcomments.js") == 1
    assert "chunk.js" not in result.stdout
    assert "Unique Vite CSS sidecar total: 1.6 KiB raw / 0.1 KiB gzip" in result.stdout


def test_unique_totals_keep_attribution(inventory):
    rows = [sizes.measure(row) for row in sizes.vite_bundles(inventory)]
    assert len([row for row in rows if row.path.name == "shared.css"]) == 2
    contents = [b"aaa", b"bbbb", b"synthetic css" * 128, b""]
    assert sizes.totals(rows) == (
        sum(map(len, contents)),
        sum(len(gzip.compress(content, compresslevel=9, mtime=0)) for content in contents),
    )
    assert sizes.totals(rows, kind="css") == (
        len(b"synthetic css" * 128),
        sum(len(gzip.compress(content, compresslevel=9, mtime=0)) for content in [b"synthetic css" * 128, b""]),
    )
    missing = next(row for row in rows if row.path.name == "missing.css")
    assert (missing.raw_bytes, missing.gzip_bytes) == (None, None)
    assert sizes.totals([missing]) == (0, 0)


@pytest.mark.parametrize("payload", ["[]", "null", "{", "42"])
def test_invalid_manifest_cli(tmp_path, payload):
    vite = tmp_path / "src/cast/static/cast/vite"
    vite.mkdir(parents=True)
    (vite / "manifest.json").write_text(payload)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(tmp_path), "--plain"], capture_output=True, text=True
    )
    assert result.returncode == 2
    assert result.stderr
