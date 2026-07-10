import json
import re

import pytest


def parse_structured_data(content):
    match = re.search(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', content, re.DOTALL)
    assert match is not None
    return json.loads(match.group(1))


class TestTwitterPlayerCard:
    pytestmark = pytest.mark.django_db

    @pytest.mark.parametrize("template_base_dir", ["bootstrap4", "plain"])
    def test_coverless_audio_episode_falls_back_to_summary(self, client, episode, template_base_dir):
        response = client.get(episode.get_url(), {"template_base_dir": template_base_dir})
        assert response.status_code == 200

        content = response.content.decode("utf-8")
        assert '<meta name="twitter:card" content="summary">' in content
        assert '<meta name="twitter:player"' not in content
        assert f'<meta name="twitter:title" content="{episode.title}">' in content
        assert '<meta property="article:published_time"' in content
        assert '<meta property="article:modified_time"' in content
        assert '<meta property="og:updated_time"' not in content
        assert '<meta property="og:audio" content="http://testserver/' in content

        structured_data = parse_structured_data(content)
        assert structured_data["@type"] == "PodcastEpisode"
        assert structured_data["name"] == episode.title
        assert "headline" not in structured_data
        assert structured_data["url"] == episode.full_url

    @pytest.mark.parametrize("template_base_dir", ["bootstrap4", "plain"])
    def test_cover_enables_player_card(self, client, episode_with_podcast_with_cover_image, template_base_dir):
        episode = episode_with_podcast_with_cover_image

        response = client.get(episode.get_url(), {"template_base_dir": template_base_dir})

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "Twitter Player Card" in content
        assert '<meta name="twitter:card" content="player">' in content
        assert '<meta name="twitter:image" content="http://testserver/' in content
        assert '<meta name="twitter:player" content="http://testserver/' in content
        assert '<meta name="twitter:player:stream" content="http://testserver/' in content
        assert '<meta property="og:audio" content="http://testserver/' in content

        structured_data = parse_structured_data(content)
        assert structured_data["@type"] == "PodcastEpisode"
