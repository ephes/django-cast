import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from cast.models import Blog, Episode, Podcast, Post
from cast.views.styleguide import (
    STYLEGUIDE_BLOG_SLUG,
    STYLEGUIDE_EPISODE_SLUG,
    STYLEGUIDE_PODCAST_SLUG,
    STYLEGUIDE_POST_SLUG_PREFIX,
)


pytestmark = [pytest.mark.django_db, pytest.mark.slow]


def test_ensure_reference_site_creates_content(site):
    """Command creates blog, podcast, posts, and episode."""
    call_command("ensure_reference_site")
    assert Blog.objects.filter(slug=STYLEGUIDE_BLOG_SLUG).exists()
    assert Podcast.objects.filter(slug=STYLEGUIDE_PODCAST_SLUG).exists()
    assert Post.objects.filter(slug__startswith=STYLEGUIDE_POST_SLUG_PREFIX).count() >= 6
    assert Episode.objects.filter(slug=STYLEGUIDE_EPISODE_SLUG).exists()


def test_ensure_reference_site_is_idempotent(site):
    """Running twice does not duplicate content."""
    call_command("ensure_reference_site")
    first_blog_count = Blog.objects.filter(slug=STYLEGUIDE_BLOG_SLUG).count()
    first_post_count = Post.objects.filter(slug__startswith=STYLEGUIDE_POST_SLUG_PREFIX).count()

    call_command("ensure_reference_site")
    assert Blog.objects.filter(slug=STYLEGUIDE_BLOG_SLUG).count() == first_blog_count
    assert Post.objects.filter(slug__startswith=STYLEGUIDE_POST_SLUG_PREFIX).count() == first_post_count


def test_ensure_reference_site_reset(site):
    """--reset deletes and recreates the reference site."""
    call_command("ensure_reference_site")
    assert Blog.objects.filter(slug=STYLEGUIDE_BLOG_SLUG).exists()

    call_command("ensure_reference_site", reset=True)
    # After reset, content is recreated
    assert Blog.objects.filter(slug=STYLEGUIDE_BLOG_SLUG).exists()


def test_ensure_reference_site_invalid_theme(site):
    """Invalid theme slug raises CommandError."""
    with pytest.raises(CommandError, match="not available"):
        call_command("ensure_reference_site", theme="nonexistent-theme")


def test_ensure_reference_site_with_theme(site):
    """--theme selects a specific theme."""
    call_command("ensure_reference_site", theme="plain")
    assert Blog.objects.filter(slug=STYLEGUIDE_BLOG_SLUG).exists()


def test_ensure_reference_site_with_renditions(site):
    """--with-renditions flag does not crash."""
    call_command("ensure_reference_site", with_renditions=True)
    assert Blog.objects.filter(slug=STYLEGUIDE_BLOG_SLUG).exists()


def test_ensure_reference_site_remote_media_flag(site, settings):
    """--remote-media enables the remote media setting."""
    # Remote media won't actually fetch (no URLs configured) but the flag should be set
    call_command("ensure_reference_site", remote_media=True)
    assert Blog.objects.filter(slug=STYLEGUIDE_BLOG_SLUG).exists()
    assert settings.CAST_STYLEGUIDE_REMOTE_MEDIA is True
