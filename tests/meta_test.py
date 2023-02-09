import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_twitter_player_blog_does_not_match(client, blog, episode):
    assert blog != episode.blog
    url = reverse("cast:twitter-player", kwargs={"blog_slug": blog.slug, "episode_slug": episode.slug})
    r = client.get(url)
    assert r.status_code == 404
