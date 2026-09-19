"""Anonymous rendering for already-authorized editor API preview requests."""

from io import BytesIO
from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.signed_cookies import SessionStore
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpRequest, HttpResponse

if TYPE_CHECKING:
    from .models import Post


def render_editor_preview(page: "Post", request: HttpRequest) -> HttpResponse:
    """Keep admission at the caller; do not forward its credentials to rendering."""
    # Construct a fresh request rather than copying user/session/auth state.
    # Only transport metadata reaches Wagtail's internal middleware request.
    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": "/",
        "SERVER_NAME": request.META.get("SERVER_NAME", "localhost"),
        "SERVER_PORT": request.get_port(),
        "HTTP_HOST": request.get_host(),
        "wsgi.url_scheme": request.scheme,
        "wsgi.input": BytesIO(),
    }
    for key in ("REMOTE_ADDR", "HTTP_X_FORWARDED_FOR", "HTTP_USER_AGENT"):
        if key in request.META:
            environ[key] = request.META[key]
    if settings.SECURE_PROXY_SSL_HEADER:
        proxy_header, _ = settings.SECURE_PROXY_SSL_HEADER
        if proxy_header in request.META:
            environ[proxy_header] = request.META[proxy_header]
    original = WSGIRequest(environ)
    original.user = AnonymousUser()
    original.session = SessionStore()
    return page.get_latest_revision_as_object().make_preview_request(
        original_request=original, extra_request_attrs={"cast_preview_as_visitor": True}
    )
