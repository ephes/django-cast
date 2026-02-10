from django.urls import reverse

from cast import appsettings
from cast.follow_links import get_follow_links


def test_get_follow_links_defaults(blog):
    blog.email = "hello@example.com"
    blog.save()

    links = get_follow_links(blog)

    assert links["rss"] == reverse("cast:latest_entries_feed", kwargs={"slug": blog.slug})
    assert links["feed_detail"] == reverse("cast:feed_detail", kwargs={"slug": blog.slug})
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
    assert links["rss"] == reverse("cast:latest_entries_feed", kwargs={"slug": blog.slug})


def test_get_follow_links_with_none_blog():
    links = get_follow_links(None)

    assert links == {}


def test_get_follow_links_empty_email(blog):
    blog.email = ""
    blog.save()

    links = get_follow_links(blog)

    assert "email" not in links


def test_get_follow_links_blog_without_slug_uses_settings_rss(blog, monkeypatch):
    monkeypatch.setattr(
        appsettings,
        "CAST_FOLLOW_LINKS",
        {"rss": "https://example.com/feed.xml"},
    )
    monkeypatch.setattr(blog, "slug", "")

    links = get_follow_links(blog)

    assert links["rss"] == "https://example.com/feed.xml"
    assert "feed_detail" not in links


def test_get_follow_links_settings_email_takes_precedence(blog, monkeypatch):
    monkeypatch.setattr(
        appsettings,
        "CAST_FOLLOW_LINKS",
        {"email": "mailto:settings@example.com"},
    )
    blog.email = "blog@example.com"
    blog.save()

    links = get_follow_links(blog)

    assert links["email"] == "mailto:settings@example.com"


def test_get_follow_links_none_blog_returns_settings(monkeypatch):
    monkeypatch.setattr(
        appsettings,
        "CAST_FOLLOW_LINKS",
        {"rss": "https://example.com/feed.xml", "mastodon": "https://example.social/@cast"},
    )

    links = get_follow_links(None)

    assert links["rss"] == "https://example.com/feed.xml"
    assert links["mastodon"] == "https://example.social/@cast"
