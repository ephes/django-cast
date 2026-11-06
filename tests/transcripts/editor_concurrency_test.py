"""Synthetic editorial interleavings, exercised on SQLite and PostgreSQL."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.core.files.base import ContentFile
from django.db import close_old_connections
from django.db.models import QuerySet
from wagtail.models import Collection

from cast.models import Audio, Contributor, Transcript, TranscriptSpeakerMapping
from cast.transcripts import services
from tests.known_speaker_apply_test import make_transcript


@pytest.mark.django_db
def test_mapping_discovery_tolerates_an_insert_after_its_empty_read(audio, monkeypatch):
    transcript = make_transcript(audio, podlove={"transcripts": [{"speaker": "Speaker 1"}]})
    contributor = Contributor.objects.create(display_name="Synthetic Speaker", slug="synthetic-speaker")
    original_iter = QuerySet.__iter__
    inserted = []

    def insert_after_read(query):
        rows = list(original_iter(query))
        if query.model is TranscriptSpeakerMapping and not rows and not inserted:
            inserted.append(True)
            TranscriptSpeakerMapping.objects.create(
                transcript=transcript,
                speaker_label="Speaker 1",
                contributor=contributor,
                review_state=TranscriptSpeakerMapping.ReviewState.APPROVED,
                source_artifact_fingerprint=transcript.mapping_fingerprint(),
            )
        return iter(rows)

    monkeypatch.setattr(QuerySet, "__iter__", insert_after_read)
    transcript.sync_speaker_mappings()
    assert inserted
    mapping = transcript.speaker_mappings.get()
    assert mapping.contributor == contributor
    assert mapping.review_state == TranscriptSpeakerMapping.ReviewState.APPROVED


@pytest.mark.django_db
def test_stale_mapping_sync_uses_current_artifacts_and_approval(audio):
    transcript = make_transcript(audio, podlove={"transcripts": [{"speaker": "Speaker 1"}]})
    stale = Transcript.objects.get(pk=transcript.pk)
    transcript.podlove.save("new.json", ContentFile(json.dumps({"transcripts": [{"speaker": "Speaker 2"}]})))
    transcript.sync_speaker_mappings()
    mapping = transcript.speaker_mappings.get(speaker_label="Speaker 2")
    mapping.display_name = "Synthetic Speaker"
    mapping.review_state = TranscriptSpeakerMapping.ReviewState.APPROVED
    mapping.save()
    stale.sync_speaker_mappings()
    mapping.refresh_from_db()
    assert mapping.active
    assert mapping.review_state == TranscriptSpeakerMapping.ReviewState.APPROVED
    assert mapping.display_name == "Synthetic Speaker"
    assert mapping.source_artifact_fingerprint == transcript.mapping_fingerprint()


@pytest.fixture
def concurrent_transcript(transactional_db, user):
    collection = Collection.get_first_root_node() or Collection.add_root(instance=Collection(name="Root"))
    audio = Audio.objects.create(user=user, collection=collection, title="Synthetic race")
    return make_transcript(audio, podlove={"transcripts": [{"speaker": "Speaker 1"}]})


def test_two_mapping_discoveries_serialize(concurrent_transcript, monkeypatch):
    transcript = concurrent_transcript
    first_read = threading.Event()
    second_started = threading.Event()
    second_read = threading.Event()
    release = threading.Event()
    original_labels = services.get_speaker_labels

    def labels(current):
        if threading.current_thread().name.endswith("_0"):
            first_read.set()
            assert release.wait(10)
        else:
            second_read.set()
        return original_labels(current)

    monkeypatch.setattr(services, "get_speaker_labels", labels)

    def sync(second=False):
        close_old_connections()
        try:
            if second:
                second_started.set()
            transcript.sync_speaker_mappings()
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(sync)
        try:
            assert first_read.wait(10)
            second = pool.submit(sync, True)
            assert second_started.wait(10)
            assert not second_read.wait(0.2)
        finally:
            release.set()
        first.result(timeout=20)
        second.result(timeout=20)
    assert transcript.speaker_mappings.count() == 1


def test_two_sidecar_edits_have_one_winner(concurrent_transcript, monkeypatch):
    transcript = concurrent_transcript
    transcript.speakers.save(
        "synthetic.speakers.json", ContentFile(json.dumps({"segments": [{"start": 0}, {"start": 1}]}))
    )
    barrier = threading.Barrier(2)
    original_save = services.save_editor_artifacts

    def save_together(*args, **kwargs):
        barrier.wait(timeout=10)
        return original_save(*args, **kwargs)

    monkeypatch.setattr(services, "save_editor_artifacts", save_together)

    def decide(position):
        close_old_connections()
        try:
            editor = Transcript.objects.get(pk=transcript.pk)
            try:
                editor.save_known_speaker_editor_decisions({position: {"action": "reject", "speaker": ""}})
            except ValueError as error:
                assert "Reload" in str(error)
                return "conflict"
            return "saved"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(decide, [0, 1]))
    assert sorted(results) == ["conflict", "saved"]
    current = Transcript.objects.get(pk=transcript.pk)
    assert len(current.get_known_speaker_editor_decisions()) == 1
