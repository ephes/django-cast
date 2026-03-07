import pytest
from django.test import override_settings
from django.urls import reverse

from .factories import BlogFactory, EpisodeFactory
from .multisite_helpers import create_site_root


@pytest.mark.django_db
def test_twitter_player(client, episode):
    episode = episode
    url = reverse("cast:twitter-player", kwargs={"episode_slug": episode.slug, "blog_slug": episode.blog.slug})
    r = client.get(url)
    assert r.status_code == 200

    content = r.content.decode("utf-8")
    assert str(episode.uuid) in content
    assert "embed.5.js" in content


@pytest.mark.django_db
def test_twitter_player_uses_current_site_for_duplicate_blog_slug(client, user, audio):
    site1, site1_root = create_site_root(
        owner=user, hostname="meta-site1.local", slug="meta-site1-root", title="Meta Site 1"
    )
    _site2, site2_root = create_site_root(
        owner=user, hostname="meta-site2.local", slug="meta-site2-root", title="Meta Site 2"
    )
    blog1 = BlogFactory(owner=user, title="Blog 1", slug="shared-meta-blog", parent=site1_root)
    blog2 = BlogFactory(owner=user, title="Blog 2", slug="shared-meta-blog", parent=site2_root)
    episode1 = EpisodeFactory(
        owner=user, title="Episode 1", slug="shared-meta-episode", parent=blog1, podcast_audio=audio
    )
    EpisodeFactory(owner=user, title="Episode 2", slug="shared-meta-episode", parent=blog2, podcast_audio=audio)

    url = reverse("cast:twitter-player", kwargs={"episode_slug": episode1.slug, "blog_slug": blog1.slug})
    with override_settings(ALLOWED_HOSTS=["testserver", site1.hostname, "meta-site2.local"]):
        response = client.get(url, HTTP_HOST=site1.hostname)

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert str(episode1.uuid) in content
