import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_components_view_disabled_returns_404(settings, client):
    """Components view returns 404 when dev tools are disabled."""
    if hasattr(settings, "CAST_ENABLE_STYLEGUIDE"):
        delattr(settings, "CAST_ENABLE_STYLEGUIDE")
    if hasattr(settings, "CAST_ENABLE_DEV_TOOLS"):
        delattr(settings, "CAST_ENABLE_DEV_TOOLS")
    response = client.get(reverse("cast:components"))
    assert response.status_code == 404


@pytest.mark.django_db
def test_components_view_enabled(settings, client):
    """Components view renders when dev tools are enabled."""
    settings.CAST_ENABLE_DEV_TOOLS = True
    response = client.get(reverse("cast:components"))
    assert response.status_code == 200
    assert "X-Robots-Tag" in response
    assert response["X-Robots-Tag"] == "noindex"
    assert b"Critical Components" in response.content


@pytest.mark.django_db
def test_theme_compare_view_disabled_returns_404(settings, client):
    """Theme compare view returns 404 when dev tools are disabled."""
    if hasattr(settings, "CAST_ENABLE_STYLEGUIDE"):
        delattr(settings, "CAST_ENABLE_STYLEGUIDE")
    if hasattr(settings, "CAST_ENABLE_DEV_TOOLS"):
        delattr(settings, "CAST_ENABLE_DEV_TOOLS")
    response = client.get(reverse("cast:theme-compare"))
    assert response.status_code == 404


@pytest.mark.django_db
def test_theme_compare_view_enabled(settings, client):
    """Theme compare view renders with iframes for each theme."""
    settings.CAST_ENABLE_DEV_TOOLS = True
    response = client.get(reverse("cast:theme-compare"))
    assert response.status_code == 200
    assert "X-Robots-Tag" in response
    assert response["X-Robots-Tag"] == "noindex"
    assert b"Theme Comparison" in response.content
    assert b"iframe" in response.content


@pytest.mark.django_db
def test_theme_compare_view_with_path(settings, client):
    """Theme compare view uses the path query param."""
    settings.CAST_ENABLE_DEV_TOOLS = True
    response = client.get(reverse("cast:theme-compare") + "?path=/styleguide-blog/")
    assert response.status_code == 200
    assert b"/styleguide-blog/" in response.content


@pytest.mark.django_db
def test_dev_health_view_disabled_returns_404(settings, client):
    """Health view returns 404 when dev tools are disabled."""
    if hasattr(settings, "CAST_ENABLE_STYLEGUIDE"):
        delattr(settings, "CAST_ENABLE_STYLEGUIDE")
    if hasattr(settings, "CAST_ENABLE_DEV_TOOLS"):
        delattr(settings, "CAST_ENABLE_DEV_TOOLS")
    response = client.get(reverse("cast:dev-health"))
    assert response.status_code == 404


@pytest.mark.django_db
def test_dev_health_view_enabled(settings, client):
    """Health view returns JSON with status and theme info."""
    settings.CAST_ENABLE_DEV_TOOLS = True
    response = client.get(reverse("cast:dev-health"))
    assert response.status_code == 200
    assert "X-Robots-Tag" in response
    assert response["X-Robots-Tag"] == "noindex"
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "ok"
    assert isinstance(data["themes"], list)
    assert data["theme_count"] >= 1


@pytest.mark.django_db
def test_dev_health_view_db_error(settings, client, mocker):
    """Health view reports database error when DB is unreachable."""
    settings.CAST_ENABLE_DEV_TOOLS = True
    mocker.patch(
        "cast.views.dev.connection.cursor",
        side_effect=Exception("connection refused"),
    )
    response = client.get(reverse("cast:dev-health"))
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "error"


@pytest.mark.django_db
def test_theme_compare_view_with_query_string(settings, client):
    """Theme compare view appends '&' when path already has a query string."""
    settings.CAST_ENABLE_DEV_TOOLS = True
    response = client.get(reverse("cast:theme-compare") + "?path=/page/%3Ffoo%3Dbar")
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    # The path has "?" in it, so iframes should use "&" to append theme
    assert "&amp;theme=" in content


@pytest.mark.django_db
def test_theme_compare_view_default_path(settings, client):
    """Theme compare view defaults to /styleguide-blog/ when no path given."""
    settings.CAST_ENABLE_DEV_TOOLS = True
    response = client.get(reverse("cast:theme-compare"))
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "/styleguide-blog/" in content


@pytest.mark.django_db
def test_theme_compare_view_rejects_absolute_url_path(settings, client):
    """Absolute URL paths are rejected and replaced with the default path."""
    settings.CAST_ENABLE_DEV_TOOLS = True
    response = client.get(reverse("cast:theme-compare") + "?path=https://example.com")
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "/styleguide-blog/" in content
    assert "https://example.com" not in content


@pytest.mark.django_db
def test_theme_compare_view_rejects_non_slash_path(settings, client):
    """Non-relative paths are rejected and replaced with the default path."""
    settings.CAST_ENABLE_DEV_TOOLS = True
    response = client.get(reverse("cast:theme-compare") + "?path=javascript:alert(1)")
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "/styleguide-blog/" in content
    assert "javascript:alert(1)" not in content


@pytest.mark.django_db
def test_theme_compare_view_rejects_protocol_relative_path(settings, client):
    """Protocol-relative paths are rejected and replaced with the default path."""
    settings.CAST_ENABLE_DEV_TOOLS = True
    response = client.get(reverse("cast:theme-compare") + "?path=//example.com/page")
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "/styleguide-blog/" in content
    assert "//example.com/page" not in content


@pytest.mark.django_db
def test_theme_compare_view_rejects_embedded_scheme(settings, client):
    """Relative-looking paths with embedded scheme markers are rejected."""
    settings.CAST_ENABLE_DEV_TOOLS = True
    response = client.get(reverse("cast:theme-compare") + "?path=/proxy/https://example.com")
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "/styleguide-blog/" in content
    assert "/proxy/https://example.com" not in content


@pytest.mark.django_db
def test_dev_views_with_deprecated_styleguide_setting(settings, client):
    """Dev views return 200 when only the deprecated CAST_ENABLE_STYLEGUIDE is set."""
    if hasattr(settings, "CAST_ENABLE_DEV_TOOLS"):
        delattr(settings, "CAST_ENABLE_DEV_TOOLS")
    settings.CAST_ENABLE_STYLEGUIDE = True
    response = client.get(reverse("cast:components"))
    assert response.status_code == 200
    response = client.get(reverse("cast:theme-compare"))
    assert response.status_code == 200
    response = client.get(reverse("cast:dev-health"))
    assert response.status_code == 200
