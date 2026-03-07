from __future__ import annotations

from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.template import TemplateDoesNotExist
from django.template.loader import get_template
from django.urls import reverse

from cast import appsettings
from cast.models import Audio, Blog
from cast.models.theme import get_template_base_dir
from cast.site_lookup import get_site_specific_page_or_404


def get_podcast_feed_urls(blog: Blog) -> list[dict[str, str]]:
    """Return a list of dicts with format, format_label, rss_url, atom_url for all audio formats."""
    feeds = []
    for audio_format in Audio.audio_formats:
        feeds.append(
            {
                "format": audio_format,
                "format_label": audio_format.upper(),
                "rss_url": reverse("cast:podcast_feed_rss", kwargs={"slug": blog.slug, "audio_format": audio_format}),
                "atom_url": reverse(
                    "cast:podcast_feed_atom", kwargs={"slug": blog.slug, "audio_format": audio_format}
                ),
            }
        )
    return feeds


def feed_detail(request: HttpRequest, slug: str) -> HttpResponse:
    """Render a feed detail page showing subscribe/feed options for a blog or podcast."""
    blog = get_site_specific_page_or_404(Blog, request, slug=slug).specific

    template_base_dir = get_template_base_dir(request, getattr(blog, "template_base_dir", None))

    context: dict[str, Any] = {
        "blog": blog,
        "is_podcast": getattr(blog, "is_podcast", False),
        "blog_feed_url": reverse("cast:latest_entries_feed", kwargs={"slug": slug}),
        "blog_atom_feed_url": reverse("cast:latest_entries_atom_feed", kwargs={"slug": slug}),
        "template_base_dir": template_base_dir,
    }

    if context["is_podcast"]:
        context["podcast_feeds"] = get_podcast_feed_urls(blog)
        follow_links: dict[str, str] = dict(appsettings.CAST_FOLLOW_LINKS)
        context["apple_podcasts_url"] = follow_links.get("apple_podcasts")
        context["spotify_url"] = follow_links.get("spotify")
        context["youtube_url"] = follow_links.get("youtube")

    template_name = _resolve_feed_detail_template(template_base_dir)
    return render(request, template_name, context)


FEED_DETAIL_FALLBACK_THEME = "plain"


def _resolve_feed_detail_template(template_base_dir: str) -> str:
    """Return the feed_detail template path, falling back to plain if needed."""
    candidate = f"cast/{template_base_dir}/feed_detail.html"
    try:
        get_template(candidate)
        return candidate
    except TemplateDoesNotExist:
        return f"cast/{FEED_DETAIL_FALLBACK_THEME}/feed_detail.html"
