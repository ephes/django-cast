import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from cast.models import Audio
from cast.voxhelm.service import resolve_audio_episode
from tests.factories import EpisodeFactory


@pytest.mark.django_db
@pytest.mark.parametrize("count", [0, 1, 2, 8])
def test_episode_uniqueness_probe_is_bounded(audio, podcast, body, count):
    episodes = [
        EpisodeFactory(
            owner=podcast.owner,
            parent=podcast,
            title=f"Synthetic {i}",
            slug=f"synthetic-{i}",
            podcast_audio=audio,
            body=body,
        )
        for i in range(count)
    ]
    with CaptureQueriesContext(connection) as queries:
        result = resolve_audio_episode(audio)
    assert result == (episodes[0] if count == 1 else None)
    assert len(queries) == 1
    assert "LIMIT 2" in queries[0]["sql"].upper()
    cached = Audio.objects.prefetch_related("episodes").get(pk=audio.pk)
    with CaptureQueriesContext(connection) as queries:
        assert resolve_audio_episode(cached) == result
        assert resolve_audio_episode(cached, episode=podcast) is podcast
    assert len(queries) == 0
