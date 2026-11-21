from datetime import time

import pytest
from django.urls import reverse
from wagtail.models import PageViewRestriction

from cast.models import ChapterMark
from cast.views import chapters


@pytest.mark.django_db
class TestPodcastChaptersJsonView:
    def _url(self, audio, *, episode_id=None):
        url = reverse("cast:chapters-json", kwargs={"pk": audio.pk})
        if episode_id is not None:
            url = f"{url}?episode_id={episode_id}"
        return url

    @pytest.mark.parametrize("method", ["post", "options"])
    def test_unsupported_methods_are_rejected_before_hydration(self, client, episode, mocker, method):
        lookup = mocker.spy(chapters, "get_object_or_404")
        hydrate = mocker.spy(chapters, "build_chapters")

        response = getattr(client, method)(self._url(episode.podcast_audio, episode_id=episode.pk))

        assert response.status_code == 405
        assert response["Allow"] == "GET, HEAD"
        lookup.assert_not_called()
        hydrate.assert_not_called()

    def test_authorized_episode_anchor_serves_chapters_json(self, client, episode):
        ChapterMark.objects.create(audio=episode.podcast_audio, start=time(0, 2, 0, 123456), title="Middle")
        ChapterMark.objects.create(audio=episode.podcast_audio, start=time(0, 1, 0), title="Intro")

        response = client.get(self._url(episode.podcast_audio, episode_id=episode.pk))

        assert response.status_code == 200
        assert response["Content-Type"] == "application/json+chapters"
        assert response.json() == {
            "version": "1.2.0",
            "chapters": [
                {"startTime": 60, "title": "Intro"},
                {"startTime": 120.123, "title": "Middle"},
            ],
        }

    @pytest.mark.parametrize("method", ["get", "head"])
    def test_login_restricted_episode_requires_login_and_prevents_caching(self, client, episode, admin_user, method):
        ChapterMark.objects.create(audio=episode.podcast_audio, start=time(0, 1, 0), title="Intro")
        PageViewRestriction.objects.create(page=episode, restriction_type=PageViewRestriction.LOGIN)
        url = self._url(episode.podcast_audio, episode_id=episode.pk)

        request = getattr(client, method)
        assert request(url).status_code == 404
        client.force_login(admin_user)
        response = request(url)

        assert response.status_code == 200
        assert response["Content-Type"] == "application/json+chapters"
        assert response["Cache-Control"] == "private, no-store"
        assert {"Cookie", "Authorization"} <= set(response["Vary"].split(", "))
        if method == "head":
            assert response.content == b""
        else:
            assert response.json()["chapters"] == [{"startTime": 60, "title": "Intro"}]

    @pytest.mark.parametrize("method", ["get", "head"])
    def test_missing_episode_id_serves_public_chapters_json(self, client, episode, method):
        ChapterMark.objects.create(audio=episode.podcast_audio, start=time(0, 1, 0), title="Intro")

        response = getattr(client, method)(self._url(episode.podcast_audio))

        assert response.status_code == 200
        assert response["Content-Type"] == "application/json+chapters"
        assert not response.has_header("Cache-Control")
        if method == "head":
            assert response.content == b""
        else:
            assert response.json() == {"version": "1.2.0", "chapters": [{"startTime": 60, "title": "Intro"}]}

    def test_mismatched_episode_id_returns_404(self, client, episode, post):
        ChapterMark.objects.create(audio=episode.podcast_audio, start=time(0, 1, 0), title="Intro")

        response = client.get(self._url(episode.podcast_audio, episode_id=post.pk))

        assert response.status_code == 404

    def test_empty_episode_id_returns_404(self, client, episode):
        ChapterMark.objects.create(audio=episode.podcast_audio, start=time(0, 1, 0), title="Intro")

        response = client.get(self._url(episode.podcast_audio, episode_id=""))

        assert response.status_code == 404

    def test_authorized_episode_anchor_serves_empty_chapters_json(self, client, episode):
        response = client.get(self._url(episode.podcast_audio, episode_id=episode.pk))

        assert response.status_code == 200
        assert response["Content-Type"] == "application/json+chapters"
        assert response.json() == {"version": "1.2.0", "chapters": []}
