import pytest


class TestTwitterPlayerCard:
    pytestmark = pytest.mark.django_db

    def test_includes_no_card_without_podcast_audio(self, client, episode):
        detail_url = episode.get_url()

        r = client.get(detail_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "html" in content
        assert episode.title in content
        assert "Twitter Player Card" not in content

    def test_includes_card_with_podcast_audio(self, client, podcast_episode):
        episode = podcast_episode
        detail_url = episode.get_url()

        r = client.get(detail_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "html" in content
        assert episode.title in content
        assert "Twitter Player Card" in content
