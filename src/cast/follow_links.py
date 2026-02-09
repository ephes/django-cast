from __future__ import annotations

from typing import TYPE_CHECKING

from django.urls import reverse

from cast import appsettings

if TYPE_CHECKING:
    from cast.models import Blog


def get_follow_links(blog: Blog | None) -> dict[str, str]:
    links: dict[str, str] = dict(appsettings.CAST_FOLLOW_LINKS)
    if blog is None:
        return links
    if blog.slug:
        links["rss"] = reverse("cast:latest_entries_feed", kwargs={"slug": blog.slug})
    if blog.email and "email" not in links:
        links["email"] = f"mailto:{blog.email}"
    return links
