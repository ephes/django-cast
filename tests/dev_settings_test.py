import warnings

import pytest

from cast.dev_settings import dev_tools_enabled


def test_dev_tools_enabled_defaults_false(settings):
    """When neither setting is defined, dev tools are disabled."""
    if hasattr(settings, "CAST_ENABLE_STYLEGUIDE"):
        delattr(settings, "CAST_ENABLE_STYLEGUIDE")
    if hasattr(settings, "CAST_ENABLE_DEV_TOOLS"):
        delattr(settings, "CAST_ENABLE_DEV_TOOLS")
    assert dev_tools_enabled() is False


def test_dev_tools_enabled_new_setting_true(settings):
    """CAST_ENABLE_DEV_TOOLS=True enables dev tools without warning."""
    if hasattr(settings, "CAST_ENABLE_STYLEGUIDE"):
        delattr(settings, "CAST_ENABLE_STYLEGUIDE")
    settings.CAST_ENABLE_DEV_TOOLS = True
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        assert dev_tools_enabled() is True
    assert len(w) == 0


def test_dev_tools_enabled_new_setting_false(settings):
    """CAST_ENABLE_DEV_TOOLS=False disables dev tools."""
    if hasattr(settings, "CAST_ENABLE_STYLEGUIDE"):
        delattr(settings, "CAST_ENABLE_STYLEGUIDE")
    settings.CAST_ENABLE_DEV_TOOLS = False
    assert dev_tools_enabled() is False


def test_dev_tools_enabled_old_setting_true_emits_warning(settings):
    """CAST_ENABLE_STYLEGUIDE=True works but emits deprecation warning."""
    if hasattr(settings, "CAST_ENABLE_DEV_TOOLS"):
        delattr(settings, "CAST_ENABLE_DEV_TOOLS")
    settings.CAST_ENABLE_STYLEGUIDE = True
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = dev_tools_enabled()
    assert result is True
    assert len(w) == 1
    assert issubclass(w[0].category, DeprecationWarning)
    assert "CAST_ENABLE_STYLEGUIDE is deprecated" in str(w[0].message)


def test_dev_tools_enabled_old_setting_false(settings):
    """CAST_ENABLE_STYLEGUIDE=False disables dev tools (with warning)."""
    if hasattr(settings, "CAST_ENABLE_DEV_TOOLS"):
        delattr(settings, "CAST_ENABLE_DEV_TOOLS")
    settings.CAST_ENABLE_STYLEGUIDE = False
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = dev_tools_enabled()
    assert result is False
    assert len(w) == 1
    assert issubclass(w[0].category, DeprecationWarning)


def test_dev_tools_enabled_both_set_new_wins(settings):
    """When both are set, CAST_ENABLE_DEV_TOOLS wins and emits a warning."""
    settings.CAST_ENABLE_STYLEGUIDE = False
    settings.CAST_ENABLE_DEV_TOOLS = True
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = dev_tools_enabled()
    assert result is True
    assert len(w) == 1
    assert issubclass(w[0].category, DeprecationWarning)
    assert "remove CAST_ENABLE_STYLEGUIDE" in str(w[0].message)


def test_dev_tools_enabled_both_set_new_false_overrides(settings):
    """When both are set, CAST_ENABLE_DEV_TOOLS=False overrides old True."""
    settings.CAST_ENABLE_STYLEGUIDE = True
    settings.CAST_ENABLE_DEV_TOOLS = False
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = dev_tools_enabled()
    assert result is False
    assert len(w) == 1


@pytest.mark.django_db
def test_styleguide_view_respects_new_setting(settings, client):
    """Styleguide view should respond to CAST_ENABLE_DEV_TOOLS."""
    from django.urls import reverse

    if hasattr(settings, "CAST_ENABLE_STYLEGUIDE"):
        delattr(settings, "CAST_ENABLE_STYLEGUIDE")
    settings.CAST_ENABLE_DEV_TOOLS = False
    response = client.get(reverse("cast:styleguide"))
    assert response.status_code == 404

    settings.CAST_ENABLE_DEV_TOOLS = True
    response = client.get(reverse("cast:styleguide"))
    assert response.status_code == 200
