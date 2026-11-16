"""Previous-version admission and transactional storage regressions (synthetic data)."""

import base64
import io
import json
from copy import deepcopy

import pytest
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile

from cast.transcripts import services, versions
from tests.transcripts.remaining_ux_test import passage_transcript

pytestmark = pytest.mark.django_db


@pytest.fixture
def versioned(episode):
    transcript = passage_transcript(episode)
    transcript.sync_speaker_mappings()
    transcript.previous_version.save("previous.json", ContentFile(versions.bundle(transcript)))
    return transcript


def state(transcript):
    transcript.refresh_from_db()
    return (
        tuple(
            (name, getattr(transcript, name).name) for name in (*services.EDITOR_ARTIFACT_FIELDS, "previous_version")
        ),
        list(transcript.speaker_mappings.values(*versions.MAPPING_FIELDS)),
        transcript.previous_version.read(),
    )


def test_capture_combined_budget_preserves_state(versioned, monkeypatch):
    before = state(versioned)
    sizes = [getattr(versioned, name).size for name in services.EDITOR_ARTIFACT_FIELDS if getattr(versioned, name)]
    monkeypatch.setattr(versions, "MAX_VERSION_ARTIFACT_BYTES", max(sizes), raising=False)
    monkeypatch.setattr(versions, "MAX_VERSION_TOTAL_BYTES", sum(sizes) - 1, raising=False)
    with pytest.raises(ValidationError):
        with versions.replacing(versioned):
            pytest.fail("capture must refuse before editing")
    assert state(versioned) == before


def test_capture_bounded_read_even_if_file_grows(versioned, monkeypatch):
    before = state(versioned)
    reads = []

    class GrowingReader(io.BytesIO):
        def read(self, size=-1):
            reads.append(size)
            assert 0 < size <= 11
            return super().read(size)

    monkeypatch.setattr(versions, "MAX_VERSION_ARTIFACT_BYTES", 10, raising=False)
    monkeypatch.setattr(versioned.podlove.storage, "size", lambda name: 1)
    with monkeypatch.context() as patch:
        patch.setattr(versioned.podlove.storage, "open", lambda *args: GrowingReader(b"x" * 11))
        with pytest.raises(ValidationError):
            versions.bundle(versioned)
    assert reads
    assert state(versioned) == before


@pytest.mark.parametrize("error", [PermissionError("private"), OSError("transport")])
def test_capture_storage_failure_is_not_missing(versioned, monkeypatch, error):
    before = state(versioned)
    with monkeypatch.context() as patch:
        patch.setattr(versioned.podlove.storage, "open", lambda *args: (_ for _ in ()).throw(error))
        with pytest.raises(ValidationError):
            with versions.replacing(versioned):
                pytest.fail("storage failures must refuse before editing")
    assert state(versioned) == before


@pytest.mark.parametrize(
    "case",
    [
        "duplicate-member",
        "duplicate-label",
        "invalid-row",
        "invalid-state",
        "bool-id",
        "active",
        "name",
        "timestamp",
        "display",
        "fingerprint",
        "target",
        "version",
        "base64",
        "deep",
        "oversize",
    ],
)
def test_restore_refuses_complete_bad_backup_before_staging(versioned, monkeypatch, case):
    payload = json.loads(versions.bundle(versioned))
    row = payload["mappings"][0]
    if case == "duplicate-label":
        payload["mappings"].append(deepcopy(row))
    elif case == "invalid-row":
        payload["mappings"].append({**row, "speaker_label": []})
    elif case == "invalid-state":
        row["review_state"] = "secret"
    elif case == "bool-id":
        row["contributor_id"] = True
    elif case == "active":
        row["active"] = 1
    elif case == "name":
        row["speaker_label"] = "x" * 257
    elif case == "timestamp":
        row["last_seen"] = "never"
    elif case == "display":
        row["display_name"] = ["name"]
    elif case == "fingerprint":
        row["source_artifact_fingerprint"] = "x" * 65
    elif case == "target":
        row.update(contributor_id=1, display_name="Also a name")
    elif case == "version":
        payload["version"] = True
    elif case == "base64":
        payload["files"]["podlove"]["content"] = "!"
    content = json.dumps(payload).encode()
    if case == "duplicate-member":
        content = content[:-1] + b', "version": 1}'
    elif case == "deep":
        content = b"[" * 100 + b"0" + b"]" * 100
    elif case == "oversize":
        monkeypatch.setattr(versions, "MAX_VERSION_JSON_BYTES", len(content) - 1, raising=False)
    versioned.previous_version.save("bad.json", ContentFile(content))
    before = state(versioned)
    from unittest.mock import patch

    with patch.object(versions.StagedFileReplacementGroup, "stage") as stage:
        with pytest.raises(ValidationError):
            versions.restore(versioned)
        stage.assert_not_called()
    assert state(versioned) == before


class Cancelled(BaseException):
    pass


@pytest.mark.parametrize("operation", ["capture", "restore"])
def test_cancellation_unwinds_owned_staged_files(versioned, monkeypatch, operation):
    before = state(versioned)
    staged = []
    original = versions.StagedFileReplacementGroup.stage
    failure = Cancelled("synthetic cancellation")

    def stage(group, *args):
        replacement = original(group, *args)
        staged.append(replacement)
        if len(staged) == (1 if operation == "capture" else 2):
            raise failure
        return replacement

    monkeypatch.setattr(versions.StagedFileReplacementGroup, "stage", stage)
    with pytest.raises(Cancelled) as caught:
        if operation == "capture":
            with versions.replacing(versioned):
                pass
        else:
            versions.restore(versioned)
    assert caught.value is failure
    assert state(versioned) == before
    assert all(not item.new_storage.exists(item.new_name) for item in staged)
    assert all(item.old_storage.exists(item.old_name) for item in staged if item.old_name)


def test_deleted_backup_cleanup_does_not_change_committed_outcome(
    versioned, monkeypatch, caplog, django_capture_on_commit_callbacks
):
    from cast.models import Transcript

    key = versioned.previous_version.name
    pk = versioned.pk
    deleted = []

    def delete(name):
        deleted.append(name)
        raise OSError("synthetic outage")

    monkeypatch.setattr(versioned.previous_version.storage, "delete", delete)
    with django_capture_on_commit_callbacks(execute=True):
        versioned.delete()
    assert not Transcript.objects.filter(pk=pk).exists()
    assert deleted == [key]
    assert key in caplog.text and "recovery storage key=" in caplog.text


def test_restore_refuses_stale_backup_generation_before_staging(versioned, monkeypatch):
    from cast.models import Transcript

    stale = Transcript.objects.get(pk=versioned.pk)
    versioned.previous_version.save("new.json", ContentFile(versions.bundle(versioned)))
    before = state(versioned)
    monkeypatch.setattr(versions.StagedFileReplacementGroup, "stage", lambda *args: pytest.fail("stale stage"))
    with pytest.raises(services.TranscriptEditConflict):
        versions.restore(stale)
    assert state(versioned) == before


@pytest.mark.parametrize(
    "case",
    [
        "root",
        "files",
        "mappings",
        "source-type",
        "source-length",
        "saved-type",
        "saved-date",
        "row",
        "row-fields",
        "label-empty",
        "label-trim",
        "contributor-negative",
        "contributor-large",
        "date-type",
        "artifact-unknown",
        "artifact-type",
        "artifact-keys",
        "filename-type",
        "filename-empty",
        "filename-path",
        "filename-windows",
        "filename-long",
        "filename-null",
        "filename-dot",
        "mapping-null",
        "source-null",
        "encoded-type",
        "encoded-long",
        "decoded-large",
        "decoded-total",
    ],
)
def test_backup_schema_domains(versioned, monkeypatch, case):
    payload = json.loads(versions.bundle(versioned))
    row = payload["mappings"][0]
    artifact = payload["files"]["podlove"]
    if case == "root":
        payload = []
    elif case == "files":
        payload["files"] = []
    elif case == "mappings":
        payload["mappings"] = {}
    elif case == "source-type":
        payload["source_fingerprint"] = 1
    elif case == "source-length":
        payload["source_fingerprint"] = "x" * 65
    elif case == "mapping-null":
        row["display_name"] = "bad\x00name"
    elif case == "source-null":
        payload["source_fingerprint"] = "bad\x00hash"
    elif case == "saved-type":
        payload["saved_at"] = 1
    elif case == "saved-date":
        payload["saved_at"] = "invalid"
    elif case == "row":
        payload["mappings"] = [None]
    elif case == "row-fields":
        del row["active"]
    elif case == "label-empty":
        row["speaker_label"] = ""
    elif case == "label-trim":
        row["speaker_label"] = " name "
    elif case == "contributor-negative":
        row["contributor_id"] = -1
    elif case == "contributor-large":
        row["contributor_id"] = 2**63
    elif case == "date-type":
        row["reviewed_at"] = True
    elif case == "artifact-unknown":
        payload["files"]["other"] = artifact
    elif case == "artifact-type":
        payload["files"]["podlove"] = []
    elif case == "artifact-keys":
        del artifact["name"]
    elif case.startswith("filename"):
        artifact["name"] = {
            "filename-type": 1,
            "filename-empty": "",
            "filename-path": "../bad.json",
            "filename-windows": "dir\\bad.json",
            "filename-long": "x" * 256,
            "filename-null": "bad\x00.json",
            "filename-dot": "..",
        }[case]
    elif case == "encoded-type":
        artifact["content"] = 1
    elif case == "encoded-long":
        monkeypatch.setattr(versions, "MAX_VERSION_ARTIFACT_BYTES", 1)
    elif case == "decoded-large":
        monkeypatch.setattr(versions, "MAX_VERSION_ARTIFACT_BYTES", 1)
        artifact["content"] = base64.b64encode(b"ab").decode()
    elif case == "decoded-total":
        monkeypatch.setattr(versions, "MAX_VERSION_TOTAL_BYTES", 1)
    versioned.previous_version.save("invalid.json", ContentFile(json.dumps(payload).encode()))
    with pytest.raises(ValidationError, match="could not be read"):
        versions.read_previous(versioned)


def test_capture_refuses_oversized_serialized_metadata(versioned, monkeypatch):
    monkeypatch.setattr(versions, "MAX_VERSION_JSON_BYTES", 1)
    before = state(versioned)
    with pytest.raises(ValidationError, match="backup limit"):
        with versions.replacing(versioned):
            pytest.fail("must refuse capture")
    assert state(versioned) == before


def test_cleanup_failure_preserves_original_cancellation(versioned, monkeypatch, caplog):
    original_rollback = versions.StagedFileReplacementGroup.rollback
    pending = []

    def broken_rollback(group):
        pending.append(group)
        raise OSError("synthetic cleanup failure")

    monkeypatch.setattr(versions.StagedFileReplacementGroup, "rollback", broken_rollback)
    cancellation = Cancelled("primary")
    with pytest.raises(Cancelled) as caught:
        with versions.replacing(versioned):
            raise cancellation
    assert caught.value is cancellation
    assert "rollback cleanup failed" in caplog.text
    for group in pending:
        original_rollback(group)


def test_restore_legacy_approved_mapping_without_deleted_target(versioned):
    payload = json.loads(versions.bundle(versioned))
    payload["mappings"][0].update(review_state="approved", contributor_id=None, display_name="")
    versioned.previous_version.save("legacy.json", ContentFile(json.dumps(payload).encode()))
    versions.restore(versioned)
    assert versioned.speaker_mappings.get().review_state == "stale"


def test_cancellation_during_storage_save_unwinds_attempted_key(versioned, monkeypatch):
    before = state(versioned)
    storage = versioned.previous_version.storage
    original_save = storage.save
    staged = []
    cancellation = Cancelled("storage save interrupted")

    def interrupted_save(name, content, **kwargs):
        staged.append(original_save(name, content, **kwargs))
        raise cancellation

    monkeypatch.setattr(storage, "save", interrupted_save)
    with pytest.raises(Cancelled) as caught:
        with versions.replacing(versioned):
            pytest.fail("save must abort")
    assert caught.value is cancellation
    assert state(versioned) == before
    assert staged and all(not storage.exists(name) for name in staged)


@pytest.mark.django_db(transaction=True)
def test_interruption_after_commit_keeps_committed_backup(versioned, monkeypatch):
    old_name = versioned.previous_version.name
    original_commit = versions.StagedFileReplacementGroup.commit
    cancellation = Cancelled("after commit")

    def interrupted_commit(group):
        original_commit(group)
        raise cancellation

    monkeypatch.setattr(versions.StagedFileReplacementGroup, "commit", interrupted_commit)
    with pytest.raises(Cancelled) as caught:
        with versions.replacing(versioned):
            pass
    assert caught.value is cancellation
    versioned.refresh_from_db()
    assert versioned.previous_version.name != old_name
    assert versioned.previous_version.storage.exists(versioned.previous_version.name)
    assert not versioned.previous_version.storage.exists(old_name)


@pytest.mark.django_db(transaction=True)
def test_cancellation_after_mapping_save_rolls_back_all_storage_and_rows(versioned, monkeypatch):
    from django.db.models import QuerySet

    from cast.models import TranscriptSpeakerMapping

    before = state(versioned)
    staged = []
    original_stage = versions.StagedFileReplacementGroup.stage
    original_create = QuerySet.create
    cancellation = Cancelled("mapping save")

    def stage(group, *args):
        replacement = original_stage(group, *args)
        staged.append(replacement)
        return replacement

    def create(query, **kwargs):
        result = original_create(query, **kwargs)
        if query.model is TranscriptSpeakerMapping:
            raise cancellation
        return result

    monkeypatch.setattr(versions.StagedFileReplacementGroup, "stage", stage)
    monkeypatch.setattr(QuerySet, "create", create)
    with pytest.raises(Cancelled) as caught:
        versions.restore(versioned)
    assert caught.value is cancellation
    assert state(versioned) == before
    assert staged and all(not item.new_storage.exists(item.new_name) for item in staged)
    assert all(item.old_storage.exists(item.old_name) for item in staged if item.old_name)
