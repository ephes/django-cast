"""Tests for cast.checks — asset freshness system check."""

import time
from pathlib import Path

import pytest
from django.core.checks import Warning
from django.core.checks.registry import registry

from cast.checks import _find_stale_assets, _newest_source_mtime, check_asset_freshness


@pytest.fixture()
def asset_tree(tmp_path):
    """Create a realistic source→built tree for freshness checks."""
    # Source dir with a .ts file
    src_dir = tmp_path / "javascript" / "src"
    src_dir.mkdir(parents=True)
    ts_file = src_dir / "main.ts"
    ts_file.write_text("export const x = 1;")

    # Built manifest
    vite_dir = tmp_path / "src" / "cast" / "static" / "cast" / "vite"
    vite_dir.mkdir(parents=True)
    manifest = vite_dir / "manifest.json"
    manifest.write_text("{}")

    # pyproject.toml so _find_stale_assets recognizes it as a repo
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")

    return tmp_path, ts_file, manifest


class TestNewestSourceMtime:
    def test_returns_none_for_empty_dir(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        assert _newest_source_mtime(empty) is None

    def test_ignores_non_source_files(self, tmp_path):
        (tmp_path / "readme.md").write_text("hello")
        assert _newest_source_mtime(tmp_path) is None

    def test_finds_newest_ts_file(self, tmp_path):
        old = tmp_path / "old.ts"
        old.write_text("old")
        time.sleep(0.05)
        new = tmp_path / "new.ts"
        new.write_text("new")
        result = _newest_source_mtime(tmp_path)
        assert result is not None
        assert result >= new.stat().st_mtime


class TestFindStaleAssets:
    def test_fresh_assets(self, asset_tree):
        repo, ts_file, manifest = asset_tree
        # Make manifest newer than source
        time.sleep(0.05)
        manifest.write_text("{}")
        assert _find_stale_assets(repo) == []

    def test_stale_assets(self, asset_tree):
        repo, ts_file, manifest = asset_tree
        # Make source newer than manifest
        time.sleep(0.05)
        ts_file.write_text("export const x = 2;")
        result = _find_stale_assets(repo)
        assert len(result) == 1
        assert "js-build-vite" in result[0]

    def test_missing_source_dir(self, tmp_path):
        """No source dir → no warnings."""
        (tmp_path / "pyproject.toml").write_text("")
        assert _find_stale_assets(tmp_path) == []

    def test_missing_manifest(self, asset_tree):
        """Source exists but no manifest → no warnings (not yet built)."""
        repo, ts_file, manifest = asset_tree
        manifest.unlink()
        assert _find_stale_assets(repo) == []


def _fake_checks_file(repo_root: Path) -> Path:
    """Create a fake src/cast/checks.py path inside a tmp repo root."""
    fake_cast = repo_root / "src" / "cast"
    fake_cast.mkdir(parents=True, exist_ok=True)
    fake_file = fake_cast / "checks.py"
    fake_file.write_text("")
    return fake_file


class TestCheckAssetFreshness:
    def test_skips_when_debug_false(self, settings):
        settings.DEBUG = False
        warnings = check_asset_freshness(None)
        assert warnings == []

    def test_skips_when_not_dev_checkout(self, settings, tmp_path, mocker):
        """No pyproject.toml above src/cast/ → skip (not a dev checkout)."""
        settings.DEBUG = True
        fake_file = _fake_checks_file(tmp_path)
        # No pyproject.toml in tmp_path
        mocker.patch("cast.checks.__file__", str(fake_file))
        warnings = check_asset_freshness(None)
        assert warnings == []

    def test_returns_warning_when_stale(self, settings, asset_tree, mocker):
        settings.DEBUG = True
        repo, ts_file, manifest = asset_tree
        fake_file = _fake_checks_file(repo)
        mocker.patch("cast.checks.__file__", str(fake_file))
        # Make source newer
        time.sleep(0.05)
        ts_file.write_text("export const x = 2;")
        warnings = check_asset_freshness(None)
        assert len(warnings) == 1
        assert isinstance(warnings[0], Warning)
        assert warnings[0].id == "cast.W001"

    def test_no_warning_when_fresh(self, settings, asset_tree, mocker):
        settings.DEBUG = True
        repo, ts_file, manifest = asset_tree
        fake_file = _fake_checks_file(repo)
        mocker.patch("cast.checks.__file__", str(fake_file))
        # Make manifest newer
        time.sleep(0.05)
        manifest.write_text("{}")
        warnings = check_asset_freshness(None)
        assert warnings == []


def test_system_check_is_registered():
    """Verify CastConfig.ready() registers check_asset_freshness.

    Merely importing cast.checks triggers @register, so the naive approach
    (check the registry) would pass even without the apps.py import.  This
    test unregisters the check, evicts the module from both sys.modules and
    the parent package attribute, calls ready(), and then verifies
    re-registration — proving the ready() → import chain works.
    """
    import sys

    import cast as cast_pkg

    # Remove the check and force module re-execution on next import
    registry.registered_checks.discard(check_asset_freshness)
    saved_module = sys.modules.pop("cast.checks")
    saved_attr = getattr(cast_pkg, "checks", None)
    if hasattr(cast_pkg, "checks"):
        delattr(cast_pkg, "checks")
    try:
        assert check_asset_freshness not in registry.get_checks(include_deployment_checks=False)

        from cast.apps import CastConfig

        CastConfig("cast", cast_pkg).ready()

        # Re-import creates a new function object, so match by qualified name
        check_names = {
            f"{c.__module__}.{c.__qualname__}" for c in registry.get_checks(include_deployment_checks=False)
        }
        assert "cast.checks.check_asset_freshness" in check_names
    finally:
        # Remove the newly registered function before restoring the original
        new_checks = {
            c
            for c in registry.registered_checks
            if getattr(c, "__module__", "") == "cast.checks"
            and getattr(c, "__qualname__", "") == "check_asset_freshness"
        }
        registry.registered_checks -= new_checks
        # Restore original state so other tests are unaffected
        sys.modules["cast.checks"] = saved_module
        if saved_attr is not None:
            cast_pkg.checks = saved_attr
        registry.registered_checks.add(check_asset_freshness)
