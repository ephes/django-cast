"""Historical migration storage failures must leave database references usable."""

import importlib
import io
from types import SimpleNamespace

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connections, transaction
from django.test import TestCase
from wagtail.models import Collection

from cast.models import Audio, Contributor, Transcript
from cast.models.contributors import ContributorVoiceReference

migration = importlib.import_module("cast.migrations.0078_private_voice_reference_storage")


class Storage:
    def __init__(self, files=None, *, fail_at=None, corrupt=False):
        self.files = dict(files or {})
        self.fail_at = fail_at
        self.corrupt = corrupt
        self.saves = 0
        self.deleted = []

    def exists(self, name):
        return name in self.files

    def open(self, name, mode="rb"):
        return io.BytesIO(self.files[name])

    def save(self, name, content, max_length=None):
        self.saves += 1
        if self.saves == self.fail_at:
            raise OSError("synthetic copy failure")
        # Simulate a backend that renames every saved key.
        name = "renamed/" + name
        assert max_length is not None and len(name) <= max_length
        self.files[name] = b"corrupt" if self.corrupt else content.read()
        return name

    def delete(self, name):
        self.deleted.append(name)
        del self.files[name]


def seed(alias):
    collection = Collection.objects.using(alias).first()
    if collection is None:
        collection = Collection.objects.using(alias).create(name="Synthetic", path="0001", depth=1, numchild=0)
    contributor = Contributor.objects.using(alias).create(display_name="Synthetic", slug="synthetic")
    reference = ContributorVoiceReference.objects.using(alias).create(contributor=contributor, clip="voice.wav")
    user = get_user_model().objects.using(alias).create(username="synthetic")
    audio = Audio(title="synthetic", user=user, collection=collection)
    audio.save(using=alias, duration=False, cache_file_sizes=False)
    transcript = Transcript.objects.using(alias).create(collection=collection, audio=audio, speakers="speakers.json")
    return reference, transcript


def run(alias):
    migration.move_voice_reference_files_to_private_storage(apps, SimpleNamespace(connection=connections[alias]))


@pytest.mark.django_db(databases=["default", "migration_other"])
def test_storage_migration_rollback_retry_collision_and_selected_alias(mocker):
    other_reference, other_transcript = seed("default")
    reference, transcript = seed("migration_other")
    public = Storage({"voice.wav": b"synthetic voice", "speakers.json": b'{"synthetic":true}'})
    private = Storage({"voice.wav": b"unrelated private object"}, fail_at=2)
    mocker.patch.object(migration, "default_storage", public)
    mocker.patch.object(migration.cast.models.contributors, "get_voice_reference_storage", return_value=private)
    with TestCase.captureOnCommitCallbacks(using="migration_other", execute=True) as callbacks:
        with pytest.raises(OSError, match="synthetic copy failure"), transaction.atomic(using="migration_other"):
            run("migration_other")
    assert not callbacks
    reference.refresh_from_db(using="migration_other")
    assert reference.clip.name == "voice.wav"
    assert public.files[reference.clip.name] == b"synthetic voice"
    assert public.deleted == []
    private.fail_at = None
    with TestCase.captureOnCommitCallbacks(using="migration_other", execute=True):
        with transaction.atomic(using="migration_other"):
            run("migration_other")
            assert public.deleted == []
    reference.refresh_from_db(using="migration_other")
    transcript.refresh_from_db(using="migration_other")
    assert private.files[reference.clip.name] == b"synthetic voice"
    assert private.files[transcript.speakers.name] == b'{"synthetic":true}'
    assert private.files["voice.wav"] == b"unrelated private object"
    # Multiple aliases may share public storage: retain originals for audited cleanup.
    assert public.deleted == []
    other_reference.refresh_from_db()
    other_transcript.refresh_from_db()
    assert other_reference.clip.name == "voice.wav"
    assert other_transcript.speakers.name == "speakers.json"


@pytest.mark.django_db
@pytest.mark.parametrize("shared_namespace", [False, True])
@pytest.mark.parametrize("retained_reference", [False, True])
def test_storage_migration_releases_only_verified_unreferenced_sources_after_commit(
    mocker, shared_namespace, retained_reference
):
    reference, transcript = seed("default")
    public = Storage({"voice.wav": b"synthetic voice", "speakers.json": b"synthetic speakers"})
    private = public if shared_namespace else Storage()
    if retained_reference:
        Transcript.objects.filter(pk=transcript.pk).update(vtt="voice.wav")
    mocker.patch.object(migration, "default_storage", public)
    mocker.patch.object(migration.cast.models.contributors, "get_voice_reference_storage", return_value=private)

    class SingleConnection:
        def __iter__(self):
            return iter(["default"])

        def __getitem__(self, alias):
            return connections[alias]

    mocker.patch.object(migration, "connections", SingleConnection())
    with TestCase.captureOnCommitCallbacks(execute=True):
        with transaction.atomic():
            run("default")
            assert public.deleted == []
    assert sorted(public.deleted) == (["speakers.json"] if retained_reference else ["speakers.json", "voice.wav"])
    reference.refresh_from_db()
    transcript.refresh_from_db()
    assert private.files[reference.clip.name] == b"synthetic voice"
    assert private.files[transcript.speakers.name] == b"synthetic speakers"


@pytest.mark.django_db
def test_storage_migration_bad_copy_preserves_original_reference(mocker):
    reference, _ = seed("default")
    public = Storage({"voice.wav": b"synthetic voice"})
    mocker.patch.object(migration, "default_storage", public)
    mocker.patch.object(
        migration.cast.models.contributors, "get_voice_reference_storage", return_value=Storage(corrupt=True)
    )
    with pytest.raises(ValueError, match="verification failed"), transaction.atomic():
        run("default")
    reference.refresh_from_db()
    assert reference.clip.name == "voice.wav"
    assert public.files["voice.wav"] == b"synthetic voice"


@pytest.mark.django_db
def test_migration_long_original_names_respect_field_limit(mocker):
    reference, _ = seed("default")
    original = "cast_voice_references/" + "x" * 70 + ".wav"
    ContributorVoiceReference.objects.filter(pk=reference.pk).update(clip=original)
    public, private = Storage({original: b"synthetic"}), Storage()
    mocker.patch.object(migration, "default_storage", public)
    mocker.patch.object(migration.cast.models.contributors, "get_voice_reference_storage", return_value=private)
    run("default")
    reference.refresh_from_db()
    assert len(reference.clip.name) <= ContributorVoiceReference._meta.get_field("clip").max_length
    assert private.files[reference.clip.name] == b"synthetic"


@pytest.mark.django_db
def test_migration_cleanup_failure_retains_originals_and_later_hooks(mocker, caplog):
    seed("default")
    public = Storage({"voice.wav": b"synthetic"})
    mocker.patch.object(migration, "default_storage", public)
    mocker.patch.object(migration.cast.models.contributors, "get_voice_reference_storage", return_value=Storage())
    mocker.patch.object(migration, "_release_source", side_effect=RuntimeError("synthetic cleanup failure"))
    later = mocker.Mock()
    with TestCase.captureOnCommitCallbacks(execute=True):
        run("default")
        transaction.on_commit(later)
    assert public.deleted == []
    later.assert_called_once()
    assert "synthetic cleanup failure" in caplog.text
