import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/check_asset_freshness.py"


def run_cli(root, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(root), *map(str, args)], capture_output=True, text=True
    )


@pytest.fixture
def asset_tree(tmp_path):
    source = tmp_path / "javascript/src"
    source.mkdir(parents=True)
    js = source / "entry.ts"
    js.write_text("synthetic source")
    os.utime(js, (1000, 1000))
    built = tmp_path / "src/cast/static/cast/vite"
    built.mkdir(parents=True)
    manifest = built / "manifest.json"
    manifest.write_text(
        json.dumps(
            {"entry": {"file": "entry.js", "css": ["entry.css"], "imports": ["chunk"]}, "chunk": {"file": "chunk.js"}}
        )
    )
    os.utime(manifest, (2000, 2000))
    for name in ["entry.js", "entry.css", "chunk.js"]:
        (built / name).write_text("synthetic output")
    return source, manifest


@pytest.mark.parametrize("option", ["--source-dir", "--manifest"])
def test_half_explicit_never_autodetects(tmp_path, asset_tree, option):
    result = run_cli(tmp_path, option, "does-not-exist")
    assert result.returncode == 2
    assert "equal numbers" in result.stdout


def test_multi_pair_verdict(tmp_path, asset_tree):
    source, manifest = asset_tree
    css = tmp_path / "cast.css"
    css.write_text("css")
    os.utime(css, (2000, 2000))
    args = ["--source-dir", source, "--manifest", manifest, "--source-dir", source, "--manifest", css]
    assert run_cli(tmp_path, *args).returncode == 0
    os.utime(css, (500, 500))
    result = run_cli(tmp_path, *args)
    assert result.returncode == 1
    assert "fresh:" in result.stdout and "STALE" in result.stdout
    assert run_cli(tmp_path, *args, "--manifest", css).returncode == 2


@pytest.mark.parametrize("name", ["entry.js", "entry.css", "chunk.js"])
def test_missing_output_fails_even_with_recent_manifest(tmp_path, asset_tree, name):
    _, manifest = asset_tree
    (manifest.parent / name).unlink()
    result = run_cli(tmp_path)
    assert result.returncode == 1
    assert name in result.stdout


@pytest.mark.parametrize(
    "payload",
    [
        "{",
        "[]",
        '{"entry":null}',
        '{"entry":{"file":"../outside.js"}}',
        '{"entry":{"file":"/outside.js"}}',
        '{"entry":{"file":"C:\\\\outside.js"}}',
        '{"entry":{"file":"entry.js","css":"entry.css"}}',
        '{"entry":{"file":"entry.js","imports":["absent"]}}',
        '{"entry":{"file":"entry.js","dynamicImports":[42]}}',
    ],
)
def test_invalid_manifest_fails(tmp_path, asset_tree, payload):
    _, manifest = asset_tree
    manifest.write_text(payload)
    os.utime(manifest, (2000, 2000))
    assert run_cli(tmp_path).returncode == 1


def test_empty_source_still_checks_outputs(tmp_path, asset_tree):
    source, manifest = asset_tree
    (source / "entry.ts").unlink()
    (manifest.parent / "entry.js").unlink()
    assert run_cli(tmp_path).returncode == 1


def test_vite_hidden_manifest_layout(tmp_path, asset_tree):
    source, manifest = asset_tree
    hidden = manifest.parent / ".vite/manifest.json"
    hidden.parent.mkdir()
    manifest.rename(hidden)
    assert run_cli(tmp_path, "--source-dir", source, "--manifest", hidden).returncode == 0


def test_missing_asset(tmp_path, asset_tree):
    _, manifest = asset_tree
    data = json.loads(manifest.read_text())
    data["entry"]["assets"] = ["missing.svg"]
    manifest.write_text(json.dumps(data))
    assert run_cli(tmp_path).returncode == 1


def test_resolved_output_escape(asset_tree, tmp_path, monkeypatch):
    from scripts.check_asset_freshness import check_freshness

    source, manifest = asset_tree
    original = Path.resolve
    target = manifest.parent / "entry.js"
    monkeypatch.setattr(Path, "resolve", lambda path: tmp_path / "outside.js" if path == target else original(path))
    fresh, message = check_freshness(source, manifest)
    assert not fresh
    assert "escapes" in message
