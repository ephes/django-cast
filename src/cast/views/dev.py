"""
Dev-only views gated by ``CAST_ENABLE_DEV_TOOLS``.

All views in this module:
- Return 404 when ``CAST_ENABLE_DEV_TOOLS`` is disabled.
- Serve ``X-Robots-Tag: noindex`` to prevent indexing.
"""

from django.db import connection
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render

from cast.dev_tools import dev_tools_enabled
from cast.models.theme import get_template_base_dir_choices

DEFAULT_THEME_COMPARE_PATH = "/styleguide-blog/"


def _check_dev_tools() -> None:
    """Raise Http404 if dev tools are not enabled."""
    if not dev_tools_enabled():
        raise Http404("Dev tools are not enabled")


def _add_noindex(response: HttpResponse) -> HttpResponse:
    """Add X-Robots-Tag: noindex header to prevent search engine indexing."""
    response["X-Robots-Tag"] = "noindex"
    return response


def _sanitize_theme_compare_path(path: str | None) -> str:
    """Return a safe relative path for theme comparison iframes."""
    if not path:
        return DEFAULT_THEME_COMPARE_PATH
    if not path.startswith("/"):
        return DEFAULT_THEME_COMPARE_PATH
    if path.startswith("//"):
        return DEFAULT_THEME_COMPARE_PATH
    if "://" in path:
        return DEFAULT_THEME_COMPARE_PATH
    return path


def components_view(request: HttpRequest) -> HttpResponse:
    """Slim critical components page for isolated testing of high-complexity widgets."""
    _check_dev_tools()
    themes = get_template_base_dir_choices()
    context = {"themes": themes}
    response = render(request, "cast/components.html", context)
    return _add_noindex(response)


def theme_compare_view(request: HttpRequest) -> HttpResponse:
    """Iframe-based theme comparison — renders one iframe per installed theme."""
    _check_dev_tools()
    path = _sanitize_theme_compare_path(request.GET.get("path"))
    themes = get_template_base_dir_choices()
    context = {
        "path": path,
        "themes": themes,
    }
    response = render(request, "cast/theme_compare.html", context)
    return _add_noindex(response)


def dev_health_view(request: HttpRequest) -> HttpResponse:
    """JSON health check for agents to verify the dev server is running."""
    _check_dev_tools()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        db_ok = True
    except Exception:
        db_ok = False

    themes = get_template_base_dir_choices()
    data = {
        "status": "ok",
        "database": "ok" if db_ok else "error",
        "themes": [{"slug": slug, "name": name} for slug, name in themes],
        "theme_count": len(themes),
    }
    response = JsonResponse(data)
    return _add_noindex(response)
