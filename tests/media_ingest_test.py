import re
import subprocess
from types import SimpleNamespace

import pytest
from django.core.cache import cache

from cast import media_ingest
from cast.models.audio import AudioDurationProbeError, AudioDurationProbeTimeout
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


class FakeField:
    def __init__(self, name: str = "clip.mp3", *, committed: bool = False) -> None:
        self.name = name
        self._committed = committed

    def __bool__(self) -> bool:
        return bool(self.name)

    def delete(self, *, save: bool) -> None:
        self.name = ""


class FakeForm:
    def __init__(self, error: Exception | None = None) -> None:
        self.instance = SimpleNamespace(
            pk=None,
            _meta=SimpleNamespace(label="cast.Fake"),
            upload=FakeField(),
            empty=FakeField(""),
            committed=FakeField("stored.mp3", committed=True),
        )
        self.error = error

    def save(self):
        if self.error is not None:
            raise self.error
        return self.instance


@pytest.mark.django_db
def test_ingest_upload_renames_files_and_applies_budget(mocker):
    form = FakeForm()
    mocker.patch("cast.media_ingest.normalize_model_save_arguments", return_value=({"using": "default"}, "default"))
    budget = mocker.patch("cast.media_ingest.media_probe_budget", wraps=media_ingest.media_probe_budget)

    result = media_ingest.ingest_upload(
        form,
        policy=media_ingest.IngestPolicy(4.5, ("upload", "empty", "committed")),
    )

    assert result is form.instance
    assert form.instance.upload.name.startswith("clip-")
    assert form.instance.upload.name.endswith(".mp3")
    assert form.instance.empty.name == ""
    assert form.instance.committed.name == "stored.mp3"
    budget.assert_called_once_with(4.5)


@pytest.mark.django_db
def test_ingest_upload_without_probe_budget(mocker):
    form = FakeForm()
    mocker.patch("cast.media_ingest.normalize_model_save_arguments", return_value=({"using": "default"}, "default"))
    budget = mocker.patch("cast.media_ingest.media_probe_budget")

    assert media_ingest.ingest_upload(form, policy=media_ingest.IngestPolicy(None, ("upload",))) is form.instance
    budget.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (subprocess.TimeoutExpired("ffprobe", 1), media_ingest.MediaProbeTimeout),
        (AudioDurationProbeTimeout("timeout"), media_ingest.MediaProbeTimeout),
        (AudioDurationProbeError("failed"), media_ingest.MediaProbeFailed),
    ],
)
def test_ingest_upload_translates_probe_errors(error, expected, mocker):
    form = FakeForm(error)
    mocker.patch("cast.media_ingest.normalize_model_save_arguments", return_value=({"using": "default"}, "default"))
    cleanup = mocker.patch("cast.media_ingest.cleanup_new_media_object", return_value=True)

    with pytest.raises(expected) as raised:
        media_ingest.ingest_upload(form, policy=media_ingest.IngestPolicy(3, ("upload",)))

    assert raised.value.__cause__ is error
    cleanup.assert_called_once_with(form.instance, ("upload",))


@pytest.mark.django_db
def test_ingest_upload_preserves_unknown_errors_and_reports_cleanup_failure(mocker):
    error = RuntimeError("save failed")
    form = FakeForm(error)
    mocker.patch("cast.media_ingest.normalize_model_save_arguments", return_value=({"using": "default"}, "default"))
    cleanup = mocker.patch("cast.media_ingest.cleanup_new_media_object", side_effect=[True, False])
    policy = media_ingest.IngestPolicy(None, ("upload",))

    with pytest.raises(RuntimeError, match="save failed"):
        media_ingest.ingest_upload(form, policy=policy)
    with pytest.raises(media_ingest.MediaIngestCleanupFailed) as raised:
        media_ingest.ingest_upload(form, policy=policy)

    assert raised.value.__cause__ is error
    assert re.fullmatch(r"clip-[0-9a-f]{12}\.mp3", form.instance.upload.name)
    assert cleanup.call_count == 2
