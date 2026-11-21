import re

import pytest
from django.test import override_settings
from django.urls import reverse
from wagtail.models import PageViewRestriction

from cast.devdata import create_transcript

from .factories import BlogFactory, EpisodeFactory, PodcastFactory
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
def test_twitter_player_draft_episode_returns_404(client, episode):
    episode.live = False
    episode.save()
    url = reverse("cast:twitter-player", kwargs={"episode_slug": episode.slug, "blog_slug": episode.blog.slug})

    response = client.get(url)

    assert response.status_code == 404


@pytest.mark.django_db
def test_twitter_player_restricted_episode_returns_404_for_anonymous(client, episode):
    PageViewRestriction.objects.create(page=episode, restriction_type=PageViewRestriction.LOGIN)
    url = reverse("cast:twitter-player", kwargs={"episode_slug": episode.slug, "blog_slug": episode.blog.slug})

    response = client.get(url)

    assert response.status_code == 404


@pytest.mark.django_db
def test_twitter_player_restricted_episode_allows_authenticated_user(client, episode, django_user_model):
    PageViewRestriction.objects.create(page=episode, restriction_type=PageViewRestriction.LOGIN)
    user = django_user_model.objects.create_user("member", password="x")
    client.force_login(user)
    url = reverse("cast:twitter-player", kwargs={"episode_slug": episode.slug, "blog_slug": episode.blog.slug})

    response = client.get(url)

    assert response.status_code == 200
    assert str(episode.uuid) in response.content.decode("utf-8")


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


@pytest.mark.django_db
@pytest.mark.parametrize("route", ["cast:twitter-player", "cast:episode-transcript"])
def test_episode_slug_must_be_unique_within_blog(client, podcast, audio, route):
    first_branch = PodcastFactory(owner=podcast.owner, parent=podcast)
    second_branch = PodcastFactory(owner=podcast.owner, parent=podcast)
    first_episode = EpisodeFactory(
        owner=podcast.owner, title="First episode", slug="shared-episode", parent=first_branch, podcast_audio=audio
    )
    second_episode = EpisodeFactory(
        owner=podcast.owner, title="Second episode", slug=first_episode.slug, parent=second_branch, podcast_audio=audio
    )
    create_transcript(
        audio=audio,
        podlove={"transcripts": [{"start": "00:00:00.000", "end": "00:00:01.000", "text": "Synthetic transcript."}]},
    )
    url = reverse(route, args=[podcast.slug, first_episode.slug])

    assert client.get(url).status_code == 404

    second_episode.unpublish()
    response = client.get(url)
    assert response.status_code == 200
    assert response.context["episode"].pk == first_episode.pk


def _twitter_player_config(content: str) -> dict:
    import json
    import re

    match = re.search(r'<script id="twitter-player-config" type="application/json">(.*?)</script>', content, re.S)
    assert match is not None, "player config must be rendered with json_script"
    return json.loads(match.group(1))


@pytest.mark.django_db
def test_twitter_player_config_is_json_not_interpolated_javascript(client, episode):
    hostile_title = "Back\\slash 'quote' \"dq\" </script><script>alert(1)</script> & co\\"
    blog = episode.blog
    blog.title = hostile_title
    blog.save()
    url = reverse("cast:twitter-player", kwargs={"episode_slug": episode.slug, "blog_slug": blog.slug})

    response = client.get(url)

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    config = _twitter_player_config(content)
    assert config["show"]["title"] == hostile_title
    assert config["show"]["url"] == blog.full_url
    assert config["duration"] == episode.podcast_audio.duration_str
    assert config["audio"] == [{"url": episode.podcast_audio.m4a.url, "mimeType": "audio/mp4"}]
    assert config["version"] == 5
    # No page data reaches executable script text, and the title cannot close a script element.
    assert "<script>alert(1)</script>" not in content
    assert content.count("</script>") == content.count("<script")
    inline_scripts = re.findall(r"<script>(.*?)</script>", content, re.S)
    assert inline_scripts == []
    assert content.index("embed.5.js") < content.index("twitter-player-bootstrap.js")


@pytest.mark.django_db
def test_twitter_player_config_without_m4a_has_empty_audio_url(client, episode):
    audio = episode.podcast_audio
    audio.m4a = None
    audio.save()
    url = reverse("cast:twitter-player", kwargs={"episode_slug": episode.slug, "blog_slug": episode.blog.slug})

    response = client.get(url)

    assert response.status_code == 200
    config = _twitter_player_config(response.content.decode("utf-8"))
    assert config["audio"] == [{"url": "", "mimeType": "audio/mp4"}]


@pytest.mark.django_db
def test_twitter_player_config_without_audio_is_empty(episode):
    from cast.views.meta import twitter_player_config

    episode.podcast_audio = None

    config = twitter_player_config(episode)

    assert config["duration"] == ""
    assert config["audio"] == [{"url": "", "mimeType": "audio/mp4"}]
    assert config["show"]["title"] == episode.blog.title
