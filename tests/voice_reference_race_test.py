"""Candidate creation on two committed connections, including SQLite's write lock."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import close_old_connections, connection
from wagtail.models import Collection

from cast.devdata import create_transcript
from cast.models import Audio, Contributor, EpisodeContributor
from cast.models.contributors import ContributorVoiceReference
from cast.transcripts import editing
from tests.voice_reference_candidate_picker_test import podlove_segment


@pytest.mark.django_db(transaction=True)
def test_identical_candidates_serialize_before_duplicate_lookup(user, monkeypatch):
    collection = Collection.get_first_root_node() or Collection.add_root(instance=Collection(name="Root"))
    audio = Audio.objects.create(user=user, collection=collection, title="Synthetic race")
    transcript = create_transcript(
        audio=audio,
        podlove={"transcripts": [podlove_segment("Alice", "1", "12"), podlove_segment("Alice", "30", "40")]},
    )
    contributor = Contributor.objects.create(display_name="Alice", slug="synthetic-race")
    context = {
        "contributor_assignments": [EpisodeContributor(contributor=contributor)],
        "source_episode": None,
        "multiple_episodes": False,
        "speaker_mappings": [],
        "speaker_labels": ["Alice"],
    }
    candidate = transcript.get_voice_reference_candidates()[0]
    first_read = threading.Event()
    second_started = threading.Event()
    second_read = threading.Event()
    release = threading.Event()
    original_lookup = editing.get_duplicate_voice_reference
    connections = []

    def lookup(**kwargs):
        result = original_lookup(**kwargs)
        if threading.current_thread().name.endswith("_0"):
            first_read.set()
            assert release.wait(10)
        else:
            second_read.set()
        return result

    monkeypatch.setattr(editing, "get_duplicate_voice_reference", lookup)

    def create(second=False):
        close_old_connections()
        try:
            connection.ensure_connection()
            connections.append(connection.connection)
            if second:
                second_started.set()
            reference, created = editing.create_voice_reference_from_candidate(
                transcript,
                context,
                candidate,
                status="pending",
                consent_confirmed=False,
            )
            return reference.pk, created
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(create)
        try:
            assert first_read.wait(10)
            second = pool.submit(create, True)
            assert second_started.wait(10)
            read_before_release = second_read.wait(0.3)
        finally:
            release.set()
        results = [first.result(timeout=20), second.result(timeout=20)]
    assert connections[0] is not connections[1]
    assert not read_before_release
    assert results[0][0] == results[1][0]
    assert [created for _, created in results] == [True, False]
    assert ContributorVoiceReference.objects.count() == 1

    # A different range or contributor keeps its own reference.
    monkeypatch.setattr(editing, "get_duplicate_voice_reference", original_lookup)
    other = Contributor.objects.create(display_name="Alice", slug="synthetic-other")
    other_context = {**context, "contributor_assignments": [EpisodeContributor(contributor=other)]}
    _, created = editing.create_voice_reference_from_candidate(
        transcript,
        other_context,
        candidate,
        status="pending",
        consent_confirmed=False,
    )
    assert created
    _, created = editing.create_voice_reference_from_candidate(
        transcript,
        context,
        transcript.get_voice_reference_candidates()[1],
        status="pending",
        consent_confirmed=False,
    )
    assert created
    assert ContributorVoiceReference.objects.count() == 3


@pytest.mark.django_db(transaction=True)
def test_source_replacement_waits_for_signed_evidence_transaction(user, monkeypatch):
    collection = Collection.get_first_root_node() or Collection.add_root(instance=Collection(name="Root"))
    audio = Audio.objects.create(user=user, collection=collection, title="Synthetic source race")
    contributor = Contributor.objects.create(display_name="Alice", slug="synthetic-source-lock")
    transcript = create_transcript(audio=audio, podlove={"transcripts": [podlove_segment("Alice", "1", "12")]})
    candidate = transcript.get_voice_reference_candidates()[0]
    context = {
        "contributor_assignments": [EpisodeContributor(contributor=contributor)],
        "source_episode": None,
        "multiple_episodes": False,
        "speaker_mappings": [],
        "speaker_labels": ["Alice"],
    }
    monkeypatch.setattr(editing, "get_speaker_mapping_context", lambda current: context)
    token = editing.sign_voice_reference_candidate(editing.transcript_evidence(transcript), candidate, contributor)
    evidence_read = threading.Event()
    replacement_started = threading.Event()
    replacement_finished = threading.Event()
    release = threading.Event()
    original_evidence = editing.transcript_evidence

    def evidence(current):
        result = original_evidence(current)
        evidence_read.set()
        assert release.wait(10)
        return result

    monkeypatch.setattr(editing, "transcript_evidence", evidence)

    def create():
        close_old_connections()
        try:
            return editing.create_voice_reference_from_candidate(
                transcript, context, candidate, status="pending", consent_confirmed=False, candidate_token=token
            )
        finally:
            close_old_connections()

    def replace():
        close_old_connections()
        try:
            replacement_started.set()
            Audio.objects.filter(pk=audio.pk).update(mp3="cast_audio/synthetic-new-generation.mp3")
            replacement_finished.set()
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(create)
        try:
            assert evidence_read.wait(10)
            second = pool.submit(replace)
            assert replacement_started.wait(10)
            assert not replacement_finished.wait(0.3)
        finally:
            release.set()
        assert first.result(timeout=20)[1]
        second.result(timeout=20)
    assert replacement_finished.is_set()
    monkeypatch.setattr(editing, "transcript_evidence", original_evidence)
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError, match="Reload"):
        editing.create_voice_reference_from_candidate(
            transcript, context, candidate, status="pending", consent_confirmed=False, candidate_token=token
        )
