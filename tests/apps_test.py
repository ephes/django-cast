from django.apps import apps
from django.test import override_settings
import pytest

import cast.appsettings as appsettings
import cast.settings as cast_settings
from cast.apps import CAST_APPS
from cast.appsettings import init_cast_settings


def test_delete_wagtail_images_app_setting(mocker):
    cast_config = apps.get_app_config("cast")
    mocked_disconnect = mocker.patch("cast.appsettings.post_delete.disconnect")

    with override_settings(DELETE_WAGTAIL_IMAGES=True):
        cast_config.ready()
    assert mocked_disconnect.call_count == 0

    mocked_disconnect.reset_mock()
    with override_settings(DELETE_WAGTAIL_IMAGES=False):
        cast_config.ready()
    assert mocked_disconnect.call_count == 1


def test_init_cast_settings_respects_override_settings_for_delete_wagtail_images(mocker):
    mocked_disconnect = mocker.patch("cast.appsettings.post_delete.disconnect")

    with override_settings(DELETE_WAGTAIL_IMAGES=False):
        init_cast_settings()

    assert mocked_disconnect.call_count == 1


def test_appsettings_dynamic_custom_themes_and_unknown_attribute():
    assert appsettings.CAST_CUSTOM_THEMES == []
    with pytest.raises(AttributeError):
        getattr(appsettings, "NONEXISTENT_SETTING")


def test_appsettings_mutable_defaults_are_not_shared(settings):
    appsettings.__dict__.pop("CAST_FOLLOW_LINKS", None)
    appsettings.__dict__.pop("CAST_IMAGE_FORMATS", None)

    settings.CAST_FOLLOW_LINKS = {}
    settings.CAST_IMAGE_FORMATS = ["jpeg", "avif"]

    follow_links = appsettings.CAST_FOLLOW_LINKS
    follow_links["example"] = "https://example.org"
    assert settings.CAST_FOLLOW_LINKS == {}
    assert "example" not in appsettings.CAST_FOLLOW_LINKS

    image_formats = appsettings.CAST_IMAGE_FORMATS
    image_formats.append("webp")
    assert settings.CAST_IMAGE_FORMATS == ["jpeg", "avif"]
    assert appsettings.CAST_IMAGE_FORMATS == ["jpeg", "avif"]


def test_appsettings_custom_themes_can_come_from_settings(settings):
    settings.CAST_CUSTOM_THEMES = [("plain", "Plain"), ("bootstrap4", "Bootstrap 4")]
    assert appsettings.CAST_CUSTOM_THEMES == [("plain", "Plain"), ("bootstrap4", "Bootstrap 4")]


def test_appsettings_new_registry_entries_resolve_at_call_time():
    with override_settings():
        assert appsettings.CAST_STYLEGUIDE_IMAGE_LIMIT == 6

    with override_settings(CAST_STYLEGUIDE_IMAGE_LIMIT=3):
        assert appsettings.CAST_STYLEGUIDE_IMAGE_LIMIT == 3


def test_test_settings_include_all_cast_apps():
    from tests import settings as test_settings

    missing_apps = [app for app in CAST_APPS if app not in test_settings.INSTALLED_APPS]
    assert missing_apps == []


def test_test_settings_include_required_api_and_htmx_apps():
    from tests import settings as test_settings

    required_apps = ["rest_framework", "django_htmx", "wagtail.api.v2"]
    missing_required_apps = [app for app in required_apps if app not in test_settings.INSTALLED_APPS]
    assert missing_required_apps == []


def test_test_settings_keep_comments_app_ordering():
    from tests import settings as test_settings

    cast_comments_index = test_settings.INSTALLED_APPS.index("cast.comments.apps.CastCommentsConfig")
    django_comments_index = test_settings.INSTALLED_APPS.index("django_comments")
    assert cast_comments_index < django_comments_index


def test_test_settings_import_from_cast_settings():
    from tests import settings as test_settings

    assert test_settings.SECRET_KEY == cast_settings.SECRET_KEY
    assert test_settings.DATABASES == cast_settings.DATABASES
    assert test_settings.TEMPLATES == cast_settings.TEMPLATES
