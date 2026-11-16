"""Package, source metadata and documentation share one version source."""

import importlib
import importlib.metadata
import runpy
import tomllib
from pathlib import Path

import cast


def test_version_matches_project_and_docs():
    root = Path(__file__).resolve().parent.parent
    expected = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    assert cast.__version__ == expected
    assert runpy.run_path(str(root / "docs/conf.py"))["release"] == expected


def test_uninstalled_version_fallback(monkeypatch):
    def missing(distribution):
        raise importlib.metadata.PackageNotFoundError(distribution)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(importlib.metadata, "version", missing)
            importlib.reload(cast)
            assert cast.__version__ == "0+unknown"
    finally:
        importlib.reload(cast)
