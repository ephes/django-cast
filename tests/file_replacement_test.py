from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from cast.file_replacement import (
    FileFieldReplacementGuard,
    StagedFileReplacement,
    StagedFileReplacementGroup,
    fresh_file_name,
)
from cast.forms import AudioForm
from cast.media_ingest import IngestPolicy, MediaIngestCleanupFailed, MediaProbeFailed, ingest_upload


@pytest.fixture(autouse=True)
def fixed_replacement_suffix(monkeypatch):
    monkeypatch.setattr(
        "cast.file_replacement.uuid4",
        lambda: SimpleNamespace(hex="123456789abcdef"),
    )


def test_fresh_file_name_preserves_directory_stem_and_compound_suffix():
    assert fresh_file_name("cast_transcript/audio.podlove.json") == ("cast_transcript/audio-123456789abc.podlove.json")
    assert fresh_file_name("cast_transcript/audio.dote.json") == "cast_transcript/audio-123456789abc.dote.json"
    assert fresh_file_name("audio.speakers.json") == "audio-123456789abc.speakers.json"
    assert fresh_file_name("audio.vtt") == "audio-123456789abc.vtt"
    assert fresh_file_name("audio") == "audio-123456789abc"


def test_fresh_file_name_replaces_existing_generated_suffix():
    assert fresh_file_name("cast_transcript/audio-aaaaaaaaaaaa.podlove.json") == (
        "cast_transcript/audio-123456789abc.podlove.json"
    )
    assert fresh_file_name("audio-aaaaaaaaaaaa-bbbbbbbbbbbb.vtt") == "audio-123456789abc.vtt"
    assert fresh_file_name("audio-aaaaaaaaaaaa") == "audio-123456789abc"


@pytest.mark.django_db
def test_staged_replacement_writes_new_saves_model_then_deletes_old(django_capture_on_commit_callbacks) -> None:
    storage = RecordingStorage(files={"old-transcript.json"})
    field = CommittedField(storage, "old-transcript.json")
    replacements = StagedFileReplacementGroup()

    replacement = replacements.stage(field, "new-transcript.json", b"new transcript")
    with django_capture_on_commit_callbacks(execute=True):
        replacements.save_model(RecordingModel(storage))
    replacements.rollback()

    assert field.name == replacement.new_name
    assert field._committed is True
    assert storage.events == [
        ("save", replacement.new_name),
        ("db_save", None),
        ("delete", "old-transcript.json"),
    ]
    assert storage.files == {replacement.new_name}


def test_staged_replacement_passes_file_field_max_length_to_storage() -> None:
    storage = RecordingStorage(files={"old-transcript.json"})
    field = MaxLengthField(storage, "old-transcript.json", max_length=100)
    replacements = StagedFileReplacementGroup()

    replacements.stage(field, "new-transcript.json", b"new transcript")

    assert storage.max_lengths == [100]


def test_staged_replacement_does_not_delete_old_file_when_upload_fails() -> None:
    storage = RecordingStorage(files={"old-transcript.json"}, fail_save_contains="new-transcript")
    field = RecordingField(storage, "old-transcript.json")
    replacements = StagedFileReplacementGroup()

    with pytest.raises(OSError, match="replacement write failed"):
        replacements.stage(field, "new-transcript.json", b"new transcript")
    replacements.rollback()

    assert field.name == "old-transcript.json"
    assert storage.files == {"old-transcript.json"}
    assert storage.events == [
        ("save", "new-transcript-123456789abc.json"),
        ("delete", "new-transcript-123456789abc.json"),
    ]


def test_grouped_replacement_failure_removes_already_written_new_files_and_keeps_old_files() -> None:
    storage = RecordingStorage(
        files={"old-podlove.json", "old-dote.json"},
        fail_save_contains="dote",
    )
    podlove = RecordingField(storage, "old-podlove.json")
    dote = RecordingField(storage, "old-dote.json")
    replacements = StagedFileReplacementGroup()

    podlove_replacement = replacements.stage(podlove, "podlove.json", b"new podlove")
    with pytest.raises(OSError, match="replacement write failed"):
        replacements.stage(dote, "dote.json", b"new dote")
    replacements.rollback()

    assert podlove.name == "old-podlove.json"
    assert dote.name == "old-dote.json"
    assert storage.files == {"old-podlove.json", "old-dote.json"}
    assert storage.events == [
        ("save", podlove_replacement.new_name),
        ("save", "dote-123456789abc.json"),
        ("delete", "dote-123456789abc.json"),
        ("delete", podlove_replacement.new_name),
    ]


@pytest.mark.django_db
def test_db_save_failure_removes_new_files_and_restores_in_memory_field_names() -> None:
    storage = RecordingStorage(files={"old-podlove.json", "old-dote.json"})
    podlove = RecordingField(storage, "old-podlove.json")
    dote = RecordingField(storage, "old-dote.json")
    replacements = StagedFileReplacementGroup()

    podlove_replacement = replacements.stage(podlove, "podlove.json", b"new podlove")
    dote_replacement = replacements.stage(dote, "dote.json", b"new dote")
    with pytest.raises(RuntimeError, match="db save failed"):
        replacements.save_model(RecordingModel(storage, fail_save=True), update_fields=["podlove", "dote"])

    assert podlove.name == "old-podlove.json"
    assert dote.name == "old-dote.json"
    assert storage.files == {"old-podlove.json", "old-dote.json"}
    assert storage.events == [
        ("save", podlove_replacement.new_name),
        ("save", dote_replacement.new_name),
        ("db_save", ("podlove", "dote")),
        ("delete", dote_replacement.new_name),
        ("delete", podlove_replacement.new_name),
    ]


def test_new_field_uses_field_save_and_rollback_removes_new_file() -> None:
    storage = RecordingStorage()
    field = UploadingField(storage, "")
    replacements = StagedFileReplacementGroup()

    replacement = replacements.stage(field, "nested/transcript.vtt", b"WEBVTT\n")
    replacements.rollback()

    assert replacement.old_name == ""
    assert replacement.new_name == "uploaded/nested/transcript-123456789abc.vtt"
    assert field.name == ""
    assert storage.files == set()
    assert storage.events == [
        ("save", "uploaded/nested/transcript-123456789abc.vtt"),
        ("delete", "uploaded/nested/transcript-123456789abc.vtt"),
    ]


@pytest.mark.django_db
def test_new_field_success_does_not_delete_old_file(django_capture_on_commit_callbacks) -> None:
    storage = RecordingStorage()
    field = UploadingField(storage, "")
    replacements = StagedFileReplacementGroup()

    replacement = replacements.stage(field, "transcript.vtt", b"WEBVTT\n")
    with django_capture_on_commit_callbacks(execute=True):
        replacements.save_model(RecordingModel(storage))

    assert field.name == replacement.new_name
    assert storage.files == {replacement.new_name}
    assert storage.events == [
        ("save", "uploaded/transcript-123456789abc.vtt"),
        ("db_save", None),
    ]


def test_staged_replacement_uses_requested_database_alias(mocker) -> None:
    storage = RecordingStorage()
    replacements = StagedFileReplacementGroup()
    model = RecordingModel(storage)
    atomic = mocker.patch("cast.file_replacement.transaction.atomic")
    on_commit = mocker.patch("cast.file_replacement.transaction.on_commit")

    replacements.save_model(model, using="archive")

    atomic.assert_called_once_with(using="archive")
    assert on_commit.call_args.kwargs == {"using": "archive"}
    assert storage.events == [("db_save", None)]


def test_rollback_restores_same_name_replacement_without_deleting_file() -> None:
    storage = RecordingStorage(files={"same-name.json"})
    field = RecordingField(storage, "replacement-name.json")
    replacements = StagedFileReplacementGroup()
    replacements.replacements.append(
        StagedFileReplacement(
            field=field,
            old_storage=storage,
            old_name="same-name.json",
            new_storage=storage,
            new_name="same-name.json",
        )
    )

    replacements.rollback()

    assert field.name == "same-name.json"
    assert storage.files == {"same-name.json"}
    assert storage.events == []


def test_failed_field_save_restores_name_and_deletes_assigned_replacement() -> None:
    storage = RecordingStorage()
    field = FailingUploadingField(storage, "")
    replacements = StagedFileReplacementGroup()

    with pytest.raises(OSError, match="field save failed"):
        replacements.stage(field, "transcript.vtt", b"WEBVTT\n")

    assert field.name == ""
    assert storage.files == set()
    assert storage.events == [
        ("save", "uploaded/transcript-123456789abc.vtt"),
        ("delete", "uploaded/transcript-123456789abc.vtt"),
        ("delete", "transcript-123456789abc.vtt"),
    ]


def test_failed_field_save_skips_second_delete_when_attempted_name_was_assigned() -> None:
    storage = RecordingStorage()
    field = FailingSameNameUploadingField(storage, "")
    replacements = StagedFileReplacementGroup()

    with pytest.raises(OSError, match="field save failed"):
        replacements.stage(field, "transcript.vtt", b"WEBVTT\n")

    assert field.name == ""
    assert storage.files == set()
    assert storage.events == [
        ("save", "transcript-123456789abc.vtt"),
        ("delete", "transcript-123456789abc.vtt"),
    ]


def _replacement_audio_form(audio, m4a_audio) -> AudioForm:
    m4a_audio.seek(0)
    replacement = SimpleUploadedFile("test.m4a", m4a_audio.read(), content_type="audio/mp4")
    form = AudioForm({"title": audio.title}, {"m4a": replacement}, instance=audio, user=audio.user)
    assert form.is_valid(), form.errors
    return form


@pytest.mark.django_db
def test_guard_snapshots_stored_name_after_form_validation(audio, m4a_audio) -> None:
    old_name = audio.m4a.name
    form = _replacement_audio_form(audio, m4a_audio)
    assert form.instance.m4a.name == "test.m4a"
    assert form.instance.m4a._committed is False

    guard = FileFieldReplacementGuard.track(form.instance, ("m4a",), using="default")
    guard.rollback()
    guard.rollback()

    assert form.instance.m4a.name == old_name
    assert type(audio).objects.get(pk=audio.pk).m4a.name == old_name


@pytest.mark.django_db
def test_guard_commit_keeps_unchanged_stored_file(audio, django_capture_on_commit_callbacks) -> None:
    old_name = audio.m4a.name
    guard = FileFieldReplacementGuard.track(audio, ("m4a",), using="default")

    with django_capture_on_commit_callbacks(execute=True):
        guard.commit()

    assert audio.m4a.storage.exists(old_name)


@pytest.mark.django_db
def test_guard_commit_ignores_old_file_delete_failure(audio, mocker, django_capture_on_commit_callbacks) -> None:
    old_name = audio.m4a.name
    storage = audio.m4a.storage
    guard = FileFieldReplacementGuard.track(audio, ("m4a",), using="default")
    audio.m4a.name = "cast_audio/replacement.m4a"
    delete = mocker.patch.object(storage, "delete", side_effect=OSError("delete failed"))

    with django_capture_on_commit_callbacks(execute=True):
        guard.commit()

    delete.assert_called_once_with(old_name)
    audio.m4a.name = old_name


@pytest.mark.django_db
def test_ingest_replacement_failure_keeps_old_row_and_file(audio, m4a_audio, mocker) -> None:
    old_name = audio.m4a.name
    storage = audio.m4a.storage
    files_before = set(storage.listdir("cast_audio")[1])
    form = _replacement_audio_form(audio, m4a_audio)
    mocker.patch(
        "cast.models.audio.run_media_probe",
        side_effect=subprocess.CalledProcessError(returncode=1, cmd="ffprobe"),
    )

    with pytest.raises(MediaProbeFailed):
        ingest_upload(form, policy=IngestPolicy(10, ("m4a", "mp3", "oga", "opus")))

    assert form.instance.m4a.name == old_name
    audio.refresh_from_db()
    assert audio.m4a.name == old_name
    assert storage.exists(old_name)
    assert set(storage.listdir("cast_audio")[1]) == files_before


@pytest.mark.django_db
def test_ingest_replacement_renames_before_overwrite_and_deletes_old_after_commit(
    audio, m4a_audio, mocker, django_capture_on_commit_callbacks
) -> None:
    old_name = audio.m4a.name
    storage = audio.m4a.storage
    mocker.patch.object(storage, "get_available_name", side_effect=lambda name, max_length=None: name)
    mocker.patch(
        "cast.models.audio.run_media_probe",
        side_effect=[
            subprocess.CompletedProcess([], 0, stdout=b"1.000000\n"),
            subprocess.CompletedProcess([], 0, stdout=b'{"chapters": []}'),
        ],
    )
    form = _replacement_audio_form(audio, m4a_audio)

    with django_capture_on_commit_callbacks(execute=True):
        result = ingest_upload(form, policy=IngestPolicy(10, ("m4a", "mp3", "oga", "opus")))

    new_path = Path(result.m4a.path)
    try:
        assert result.m4a.name != old_name
        assert storage.exists(result.m4a.name)
        assert not storage.exists(old_name)
    finally:
        new_path.unlink(missing_ok=True)


@pytest.mark.django_db
def test_ingest_replacement_reports_strict_cleanup_failure(audio, m4a_audio, mocker) -> None:
    old_name = audio.m4a.name
    storage = audio.m4a.storage
    files_before = set(storage.listdir("cast_audio")[1])
    form = _replacement_audio_form(audio, m4a_audio)
    mocker.patch("cast.models.audio.run_media_probe", return_value=subprocess.CompletedProcess([], 0, stdout=b"N/A\n"))
    mocker.patch.object(storage, "delete", side_effect=OSError("delete failed"))

    with pytest.raises(MediaIngestCleanupFailed):
        ingest_upload(form, policy=IngestPolicy(10, ("m4a", "mp3", "oga", "opus")))

    assert form.instance.m4a.name == old_name
    audio.refresh_from_db()
    assert audio.m4a.name == old_name
    files_after = set(storage.listdir("cast_audio")[1])
    new_paths = [Path(storage.path(f"cast_audio/{name}")) for name in files_after - files_before]
    try:
        assert len(new_paths) == 1
    finally:
        for path in new_paths:
            path.unlink(missing_ok=True)


class RecordingStorage:
    def __init__(self, *, files: set[str] | None = None, fail_save_contains: str = "") -> None:
        self.events: list[tuple[str, object]] = []
        self.max_lengths: list[int | None] = []
        self.files = set(files or set())
        self.fail_save_contains = fail_save_contains

    def save(self, name: str, _content, *, max_length: int | None = None) -> str:
        self.max_lengths.append(max_length)
        self.events.append(("save", name))
        if self.fail_save_contains and self.fail_save_contains in name:
            raise OSError("replacement write failed")
        self.files.add(name)
        return name

    def delete(self, name: str) -> None:
        self.events.append(("delete", name))
        self.files.discard(name)


class RecordingField:
    def __init__(self, storage: RecordingStorage, name: str) -> None:
        self.storage = storage
        self.name = name


class CommittedField(RecordingField):
    def __init__(self, storage: RecordingStorage, name: str) -> None:
        super().__init__(storage, name)
        self._committed = False


class MaxLengthField(RecordingField):
    def __init__(self, storage: RecordingStorage, name: str, *, max_length: int) -> None:
        super().__init__(storage, name)
        self.field = SimpleNamespace(max_length=max_length)


class UploadingField(RecordingField):
    def save(self, name: str, content, *, save: bool) -> None:
        assert save is False
        self.name = self.storage.save(f"uploaded/{name}", content)


class FailingUploadingField(UploadingField):
    def save(self, name: str, content, *, save: bool) -> None:
        super().save(name, content, save=save)
        raise OSError("field save failed")


class FailingSameNameUploadingField(UploadingField):
    def save(self, name: str, content, *, save: bool) -> None:
        assert save is False
        self.name = self.storage.save(name, content)
        raise OSError("field save failed")


class RecordingModel:
    def __init__(self, storage: RecordingStorage, *, fail_save: bool = False) -> None:
        self.storage = storage
        self.fail_save = fail_save

    def save(self, *args, **kwargs) -> None:
        del args
        update_fields = kwargs.get("update_fields")
        self.storage.events.append(("db_save", tuple(update_fields) if update_fields is not None else None))
        if self.fail_save:
            raise RuntimeError("db save failed")
