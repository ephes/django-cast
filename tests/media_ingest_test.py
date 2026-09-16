import pytest
from django.core.cache import cache

from cast import media_ingest
from tests.factories import UserFactory


class TestUploadLock:
    pytestmark = pytest.mark.django_db

    def test_uses_owner_token_and_requested_ttl(self, mocker):
        user = UserFactory()
        cache_mock = mocker.patch("cast.media_ingest.cache")
        cache_mock.add.return_value = True

        with media_ingest.upload_lock(user, seconds=45):
            owner = cache_mock.add.call_args.args[1]
            cache_mock.get.return_value = owner
            assert len(owner) == 32

        cache_mock.add.assert_called_once_with(f"cast:editor-media-upload:{user.pk}", owner, timeout=45)
        cache_mock.delete.assert_called_once_with(f"cast:editor-media-upload:{user.pk}")

    def test_does_not_release_a_successor_lock(self):
        user = UserFactory()
        key = f"cast:editor-media-upload:{user.pk}"
        cache.delete(key)

        with media_ingest.upload_lock(user):
            cache.set(key, "successor", timeout=60)

        assert cache.get(key) == "successor"
        cache.delete(key)

    def test_nested_lock_is_refused(self):
        user = UserFactory()
        key = f"cast:editor-media-upload:{user.pk}"
        cache.delete(key)

        with media_ingest.upload_lock(user):
            with pytest.raises(media_ingest.MediaUploadInProgress):
                with media_ingest.upload_lock(user):
                    pass

        assert cache.get(key) is None


def test_policies_read_current_settings(settings):
    settings.CAST_EDITOR_MEDIA_PROBE_SECONDS = 3.5
    settings.CAST_MEDIA_PROBE_SECONDS = 12.5

    assert media_ingest.editor_policy(("m4a",)) == media_ingest.IngestPolicy(3.5, ("m4a",))
    assert media_ingest.admin_policy(("original", "poster")) == media_ingest.IngestPolicy(12.5, ("original", "poster"))
    assert media_ingest.TRANSCRIPT_POLICY == media_ingest.IngestPolicy(None, ("podlove", "dote", "vtt"))
