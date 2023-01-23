import pytest
from django.core.files.storage import default_storage

from cast.utils import storage_walk_paths


class TestUtils:
    @pytest.mark.django_db
    def test_walk_fs_paths(self, client, podcast_episode):
        audio_path = podcast_episode.podcast_audio.m4a.path
        found = False
        for path in storage_walk_paths(default_storage):
            if audio_path.endswith(path):
                found = True
        assert found
