from django.urls import reverse

from cast import appsettings
from cast.follow_links import get_follow_links


def test_get_follow_links_defaults(blog):
    blog.email = "hello@example.com"
    blog.save()

    links = get_follow_links(blog)

    assert links["rss"] == reverse("cast:latest_entries_feed", kwargs={"slug": blog.slug})
    assert links["email"] == "mailto:hello@example.com"


def test_get_follow_links_settings_override(blog, monkeypatch):
    monkeypatch.setattr(
        appsettings,
        "CAST_FOLLOW_LINKS",
        {
            "mastodon": "https://example.social/@cast",
            "rss": "https://example.com/feed.xml",
        },
    )

    links = get_follow_links(blog)

    assert links["mastodon"] == "https://example.social/@cast"
    assert links["rss"] == "https://example.com/feed.xml"


def test_get_follow_links_with_none_blog():
    links = get_follow_links(None)

    assert links == {}


def test_get_follow_links_empty_email(blog):
    blog.email = ""
    blog.save()

    links = get_follow_links(blog)

    assert "email" not in links
