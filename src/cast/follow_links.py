"""Build "follow" link dicts for blog subscription options.

Produces a mapping of link type (e.g. ``"rss"``, ``"email"``,
``"feed_detail"``) to URL, used by templates to render subscription
buttons and follow links. Starts from the global
``CAST_FOLLOW_LINKS`` setting and augments with blog-specific RSS
feed and email links.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.urls import reverse

from cast import appsettings

if TYPE_CHECKING:
    from cast.models import Blog


def get_follow_links(blog: Blog | None) -> dict[str, str]:
    """Return follow/subscribe links for the given blog.

    Start from the site-wide ``CAST_FOLLOW_LINKS`` setting, then add
    the blog's RSS feed URL and email contact if available. When
    *blog* is ``None``, only the global links are returned.
    """
    links: dict[str, str] = dict(appsettings.CAST_FOLLOW_LINKS)
    if blog is None:
        return links
    if blog.slug:
        links["rss"] = reverse("cast:latest_entries_feed", kwargs={"slug": blog.slug})
        links["feed_detail"] = reverse("cast:feed_detail", kwargs={"slug": blog.slug})
    if blog.email and "email" not in links:
        links["email"] = f"mailto:{blog.email}"
    return links
