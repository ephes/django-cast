from __future__ import annotations

from typing import TYPE_CHECKING, cast

from django.http import HttpRequest
from django.utils.html import escape

from cast.http_types import HtmxHttpRequest

if TYPE_CHECKING:
    from cast.models.pages import Post
    from cast.models.repository import PostDetailContext


def render_post_description(
    post: Post,
    *,
    request: HttpRequest,
    render_detail: bool = False,
    render_for_feed: bool = True,
    escape_html: bool = True,
    remove_newlines: bool = True,
    repository: PostDetailContext | None = None,
) -> str:
    """Render a post body for feeds, API fields, and compatibility callers."""
    htmx_request = cast(HtmxHttpRequest, request)
    if repository is None:
        repository = post.get_repository(htmx_request, {})
    description = post.serve(
        htmx_request,
        render_detail=render_detail,
        repository=repository,
        render_for_feed=render_for_feed,
        local_template_name="post_body.html",
    ).rendered_content
    if remove_newlines:
        description = description.replace("\n", "")
    if escape_html:
        description = escape(description)
    return description
