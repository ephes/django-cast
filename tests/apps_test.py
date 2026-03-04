from django.apps import apps
from django.test import override_settings
import pytest

import cast.appsettings as appsettings
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
