import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_twitter_player(client, podcast_episode):
    episode = podcast_episode
    url = reverse("cast:twitter-player", kwargs={"episode_slug": episode.slug, "blog_slug": episode.blog.slug})
    r = client.get(url)
    assert r.status_code == 200

    content = r.content.decode("utf-8")
    assert str(episode.uuid) in content
    assert "embed.5.js" in content
