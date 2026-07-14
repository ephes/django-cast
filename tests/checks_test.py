"""Tests for cast.checks — asset freshness system check."""

import os
import time
from pathlib import Path

import pytest
from django.core.checks import Warning
from django.core.checks.registry import registry

from cast.appsettings import CAST_SETTING_REGISTRY
from cast.apps import CAST_MIDDLEWARE
from cast.checks import CAST_SETTING_TYPES, _find_stale_assets, _newest_source_mtime, check_asset_freshness
from cast.checks import check_cast_comments_ordering, check_cast_required_middleware, check_cast_setting_types
from cast.checks import check_post_body_block_setting


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

    def test_returns_newest_among_multiple(self, tmp_path):
        """Ensure the newest mtime is returned regardless of iteration order."""
        new = tmp_path / "new.ts"
        new.write_text("new")
        older = tmp_path / "older.tsx"
        older.write_text("older")
        # Set explicit mtimes so the test is fully deterministic
        os.utime(new, (2, 2))
        os.utime(older, (1, 1))
        result = _newest_source_mtime(tmp_path)
        assert result == 2.0


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


class TestCheckCastSettingTypes:
    def test_cast_setting_types_are_derived_from_registry_without_changing_scope(self):
        expected = (
            ("CAST_COMMENTS_ENABLED", bool),
            ("CAST_COMMENTS_ALLOW_AUTHOR_EDITS", bool),
            ("CAST_CUSTOM_THEMES", list),
            ("CAST_FOLLOW_LINKS", dict),
            ("CAST_FILTERSET_FACETS", list),
            ("CAST_IMAGE_FORMATS", list),
            ("CAST_REGULAR_IMAGE_SLOT_DIMENSIONS", list),
            ("CAST_GALLERY_IMAGE_SLOT_DIMENSIONS", list),
            ("CAST_GALLERY_THUMBNAIL_RENDITIONS_SRGB", bool),
            ("CAST_REPOSITORY", str),
            ("CAST_PODLOVE_PLAYER_THEMES", dict),
            ("CAST_AUDIO_PLAYER", str),
        )
        derived = tuple(
            (name, setting.check_type)
            for name, setting in CAST_SETTING_REGISTRY.items()
            if setting.check_type is not None
        )

        assert CAST_SETTING_TYPES == expected
        assert derived == expected

    def test_valid_cast_settings(self, settings):
        settings.CAST_COMMENTS_ENABLED = True
        settings.CAST_CUSTOM_THEMES = [("plain", "Plain")]
        settings.CAST_FOLLOW_LINKS = {"apple_podcasts": "https://example.com"}
        settings.CAST_FILTERSET_FACETS = ["search"]
        settings.CAST_IMAGE_FORMATS = ["jpeg", "avif"]
        settings.CAST_REGULAR_IMAGE_SLOT_DIMENSIONS = [(1110, 740)]
        settings.CAST_GALLERY_IMAGE_SLOT_DIMENSIONS = [(1110, 740), (120, 80)]
        settings.CAST_GALLERY_THUMBNAIL_RENDITIONS_SRGB = True
        settings.CAST_REPOSITORY = "default"
        settings.CAST_PODLOVE_PLAYER_THEMES = {"default": {"main": "#333"}}

        assert check_cast_setting_types(None) == []

    def test_invalid_cast_setting_type_returns_error(self, settings):
        settings.CAST_IMAGE_FORMATS = "jpeg"

        errors = check_cast_setting_types(None)

        assert len(errors) == 1
        assert errors[0].id == "cast.E001"
        assert "CAST_IMAGE_FORMATS must be of type list." == errors[0].msg


class TestCheckPostBodyBlockSetting:
    def test_missing_or_valid_setting(self, settings):
        settings.CAST_POST_BODY_BLOCKS = None
        assert check_post_body_block_setting(None) == []

        settings.CAST_POST_BODY_BLOCKS = {
            "overview": ("tests.custom_post_body_blocks.overview_callout_block",),
            "detail": ["tests.custom_post_body_blocks.detail_callout_block"],
        }
        assert check_post_body_block_setting(None) == []

    @pytest.mark.parametrize(
        "configured, expected_message",
        [
            ("not-a-dict", "must be a dict"),
            ({"teaser": []}, "unsupported section 'teaser'"),
            ({"detail": "tests.custom_post_body_blocks.detail_callout_block"}, "must be a list or tuple"),
            ({"detail": [None]}, "must be a non-empty dotted factory path string"),
            ({"detail": ["tests.custom_post_body_blocks.missing"]}, "could not import"),
            ({"detail": ["tests.custom_post_body_blocks.not_callable"]}, "must point to a callable factory"),
            ({"detail": ["tests.custom_post_body_blocks.raising_block"]}, "raised RuntimeError"),
            ({"detail": ["tests.custom_post_body_blocks.invalid_shape_block"]}, "must return a two-item tuple"),
            ({"detail": ["tests.custom_post_body_blocks.non_string_name_block"]}, "non-string block name"),
            ({"detail": ["tests.custom_post_body_blocks.empty_name_block"]}, "empty block name"),
            ({"detail": ["tests.custom_post_body_blocks.invalid_block_instance"]}, "expected a wagtail.blocks.Block"),
            ({"detail": ["tests.custom_post_body_blocks.paragraph_collision_block"]}, "collides"),
            (
                {
                    "detail": [
                        "tests.custom_post_body_blocks.detail_callout_block",
                        "tests.custom_post_body_blocks.repeated_detail_callout_block",
                    ]
                },
                "is duplicated",
            ),
        ],
    )
    def test_invalid_setting_returns_actionable_error(self, settings, configured, expected_message):
        settings.CAST_POST_BODY_BLOCKS = configured

        errors = check_post_body_block_setting(None)

        assert len(errors) == 1
        assert errors[0].id == "cast.E004"
        assert expected_message in errors[0].msg
        assert "dotted no-argument factories" in errors[0].hint


class TestCheckCastConfiguration:
    def test_cast_comments_must_be_before_django_comments(self, settings, mocker):
        apps = list(settings.INSTALLED_APPS)
        apps.remove("cast.comments.apps.CastCommentsConfig")
        django_comments_index = apps.index("django_comments")
        apps.insert(django_comments_index + 1, "cast.comments.apps.CastCommentsConfig")
        mocker.patch("cast.checks.settings.INSTALLED_APPS", apps)

        errors = check_cast_comments_ordering(None)

        assert len(errors) == 1
        assert errors[0].id == "cast.E002"
        assert "before 'django_comments'" in errors[0].msg

    def test_required_cast_middleware_missing(self, settings, mocker):
        middleware = [mw for mw in settings.MIDDLEWARE if mw != "django_htmx.middleware.HtmxMiddleware"]
        mocker.patch("cast.checks.settings.MIDDLEWARE", middleware)

        errors = check_cast_required_middleware(None)

        assert len(errors) == 1
        assert errors[0].id == "cast.E003"
        assert "django_htmx.middleware.HtmxMiddleware" in errors[0].msg

    def test_cast_comments_ordering_with_django_comments_config_path(self, settings, mocker):
        apps = list(settings.INSTALLED_APPS)
        django_comments_index = apps.index("django_comments")
        apps[django_comments_index] = "django_comments.apps.CommentsConfig"
        apps.remove("cast.comments.apps.CastCommentsConfig")
        apps.insert(django_comments_index + 1, "cast.comments.apps.CastCommentsConfig")
        mocker.patch("cast.checks.settings.INSTALLED_APPS", apps)

        errors = check_cast_comments_ordering(None)

        assert len(errors) == 1
        assert errors[0].id == "cast.E002"
        assert "INSTALLED_APPS" in errors[0].msg

    def test_cast_comments_ordering_skips_when_cast_comments_absent(self, settings, mocker):
        apps = [
            app
            for app in settings.INSTALLED_APPS
            if app not in {"cast.comments", "cast.comments.apps.CastCommentsConfig"}
        ]
        mocker.patch("cast.checks.settings.INSTALLED_APPS", apps)

        assert check_cast_comments_ordering(None) == []

    def test_cast_comments_ordering_skips_when_django_comments_absent(self, settings, mocker):
        apps = [app for app in settings.INSTALLED_APPS if app != "django_comments"]
        mocker.patch("cast.checks.settings.INSTALLED_APPS", apps)

        assert check_cast_comments_ordering(None) == []

    def test_cast_configuration_checks_pass_when_valid(self, settings, mocker):
        middleware = list(CAST_MIDDLEWARE) + [mw for mw in settings.MIDDLEWARE if mw not in CAST_MIDDLEWARE]
        mocker.patch("cast.checks.settings.MIDDLEWARE", middleware)

        assert check_cast_comments_ordering(None) == []
        assert check_cast_required_middleware(None) == []

    def test_required_cast_middleware_all_missing(self, settings, mocker):
        middleware = [mw for mw in settings.MIDDLEWARE if mw not in set(CAST_MIDDLEWARE)]
        mocker.patch("cast.checks.settings.MIDDLEWARE", middleware)

        errors = check_cast_required_middleware(None)

        assert len(errors) == 1
        assert errors[0].id == "cast.E003"
        for middleware_entry in CAST_MIDDLEWARE:
            assert middleware_entry in errors[0].msg


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

    # Save all originally registered cast.checks functions
    original_cast_checks = {c for c in registry.registered_checks if getattr(c, "__module__", "") == "cast.checks"}

    # Remove all cast.checks registrations and force module re-execution on next import
    registry.registered_checks -= original_cast_checks
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
        # Remove the newly registered functions before restoring originals
        new_checks = {c for c in registry.registered_checks if getattr(c, "__module__", "") == "cast.checks"}
        registry.registered_checks -= new_checks
        # Restore original state so other tests are unaffected
        sys.modules["cast.checks"] = saved_module
        if saved_attr is not None:
            cast_pkg.checks = saved_attr
        registry.registered_checks |= original_cast_checks
