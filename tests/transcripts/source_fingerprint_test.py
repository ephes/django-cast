"""Speaker mappings are reviewed against the artifacts as received, not the current file bytes."""

import importlib
import json
from functools import partial
from types import SimpleNamespace

import pytest
from django import VERSION as DJANGO_VERSION
from django.apps import apps
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.urls import reverse

from cast.devdata import create_transcript
from cast.file_replacement import StagedFileReplacementGroup
from cast.media_derivation import save_transcript_with_derivations
from cast.models import Transcript, TranscriptSpeakerMapping
from cast.transcript_sanitization import _current_mapping_rows
from cast.voxhelm import VoxhelmTranscriptService

PODLOVE = {
    "transcripts": [
        {"start": "00:00:10.000", "start_ms": 10000, "speaker": "Speaker 1", "voice": "Speaker 1", "text": "a"},
        {"start": "00:00:12.500", "start_ms": 12500, "speaker": "Speaker 2", "voice": "Speaker 2", "text": "b"},
    ]
}
DOTE = {
    "lines": [
        {"startTime": "00:00:10,000", "endTime": "00:00:12,500", "speakerDesignation": "Speaker 1", "text": "a"},
        {"startTime": "00:00:12,500", "endTime": "00:00:13,000", "speakerDesignation": "Speaker 2", "text": "b"},
    ]
}
VTT = "WEBVTT\n\n00:00:10.000 --> 00:00:12.500\n<v Speaker 1>a</v>\n\n00:00:12.500 --> 00:00:13.000\n<v Speaker 2>b</v>\n"
SPEAKERS = {
    "summary": {"strategy": "pyannote_known_speaker"},
    "segments": [{"index": 1, "start": 12.5, "speaker": "Johannes", "speaker_uncertain": False}],
}


@pytest.fixture()
def received_transcript(audio):
    transcript = create_transcript(audio=audio, podlove=PODLOVE, dote=DOTE, vtt=VTT)
    transcript.speakers.save("t.speakers.json", ContentFile(json.dumps(SPEAKERS).encode()), save=False)
    transcript.save(update_fields=["speakers"])
    return transcript


def approve(transcript, speaker_label, display_name):
    mapping = transcript.speaker_mappings.get(speaker_label=speaker_label)
    mapping.display_name = display_name
    mapping.review_state = TranscriptSpeakerMapping.ReviewState.APPROVED
    mapping.source_artifact_fingerprint = transcript.mapping_fingerprint()
    mapping.save()
    return mapping


def assert_current(transcript, mapping):
    transcript.sync_speaker_mappings()
    mapping.refresh_from_db()
    assert mapping.review_state == TranscriptSpeakerMapping.ReviewState.APPROVED
    assert mapping.is_current_for_fingerprint(transcript.mapping_fingerprint())
    assert mapping in _current_mapping_rows(Transcript.objects.get(pk=transcript.pk))


def assert_stale(transcript, mapping):
    transcript.sync_speaker_mappings()
    mapping.refresh_from_db()
    assert mapping.review_state == TranscriptSpeakerMapping.ReviewState.STALE
    assert _current_mapping_rows(Transcript.objects.get(pk=transcript.pk)) == []


class TestTranscriptSourceFingerprint:
    pytestmark = pytest.mark.django_db

    def test_storing_artifacts_records_the_received_fingerprint(self, received_transcript):
        transcript = Transcript.objects.get(pk=received_transcript.pk)

        assert transcript.source_fingerprint
        assert transcript.source_fingerprint == transcript.transcript_artifact_fingerprint()
        assert transcript.mapping_fingerprint() == transcript.source_fingerprint

    def test_transcript_without_artifacts_has_empty_fingerprint(self, audio):
        transcript = create_transcript(audio=audio)

        assert transcript.source_fingerprint == ""
        assert transcript.mapping_fingerprint() == ""

    def test_mapping_fingerprint_falls_back_to_current_artifacts(self, received_transcript):
        Transcript.objects.filter(pk=received_transcript.pk).update(source_fingerprint="")
        transcript = Transcript.objects.get(pk=received_transcript.pk)

        assert transcript.mapping_fingerprint() == transcript.transcript_artifact_fingerprint()

    def test_approved_mapping_stays_current_after_applying_known_speakers(self, received_transcript):
        mapping = approve(received_transcript, "Speaker 1", "Alice")
        source_fingerprint = received_transcript.source_fingerprint

        assert received_transcript.apply_known_speaker_suggestions(smooth=False) > 0

        transcript = Transcript.objects.get(pk=received_transcript.pk)
        assert transcript.podlove_data["transcripts"][1]["speaker"] == "Johannes"
        assert transcript.transcript_artifact_fingerprint() != source_fingerprint
        assert transcript.source_fingerprint == source_fingerprint
        assert_current(transcript, mapping)

    def test_approved_mapping_stays_current_after_rewriting_speaker_labels(self, received_transcript):
        mapping = approve(received_transcript, "Speaker 1", "Alice")
        source_fingerprint = received_transcript.source_fingerprint

        assert received_transcript.rewrite_speaker_labels({"Speaker 2": "Bob"})

        transcript = Transcript.objects.get(pk=received_transcript.pk)
        assert transcript.source_fingerprint == source_fingerprint
        assert_current(transcript, mapping)

    def test_approved_mapping_stays_current_after_artifact_text_rewrite(self, received_transcript):
        mapping = approve(received_transcript, "Speaker 1", "Alice")
        source_fingerprint = received_transcript.source_fingerprint
        corrected = json.loads(json.dumps(PODLOVE))
        corrected["transcripts"][0]["text"] = "corrected"
        replacements = StagedFileReplacementGroup()
        received_transcript._save_json_file("podlove", corrected, replacements=replacements)

        replacements.save_model(
            received_transcript,
            update_fields=["podlove"],
            save=partial(save_transcript_with_derivations, preserve_source_fingerprint=True),
        )

        transcript = Transcript.objects.get(pk=received_transcript.pk)
        assert transcript.podlove_data["transcripts"][0]["text"] == "corrected"
        assert transcript.source_fingerprint == source_fingerprint
        assert_current(transcript, mapping)

    def test_metadata_only_save_keeps_fingerprint(self, received_transcript):
        mapping = approve(received_transcript, "Speaker 1", "Alice")
        received_transcript.apply_known_speaker_suggestions(smooth=False)
        transcript = Transcript.objects.get(pk=received_transcript.pk)
        source_fingerprint = transcript.source_fingerprint

        save_transcript_with_derivations(transcript)

        transcript.refresh_from_db()
        assert transcript.source_fingerprint == source_fingerprint
        assert_current(transcript, mapping)

    def test_voxhelm_import_records_new_fingerprint_and_marks_mappings_stale(self, received_transcript):
        mapping = approve(received_transcript, "Speaker 1", "Alice")
        source_fingerprint = received_transcript.source_fingerprint
        podlove = json.loads(json.dumps(PODLOVE))
        podlove["transcripts"][0]["text"] = "regenerated"

        VoxhelmTranscriptService._save_artifacts(
            transcript=received_transcript,
            audio=received_transcript.audio,
            podlove=json.dumps(podlove).encode(),
            dote=json.dumps(DOTE).encode(),
            vtt=VTT.encode(),
        )

        transcript = Transcript.objects.get(pk=received_transcript.pk)
        assert transcript.source_fingerprint != source_fingerprint
        assert transcript.source_fingerprint == transcript.transcript_artifact_fingerprint()
        assert_stale(transcript, mapping)

    def test_admin_upload_records_new_fingerprint_and_marks_mappings_stale(self, admin_client, received_transcript):
        mapping = approve(received_transcript, "Speaker 1", "Alice")
        source_fingerprint = received_transcript.source_fingerprint
        podlove = json.loads(json.dumps(PODLOVE))
        podlove["transcripts"][0]["text"] = "uploaded"
        uploads = {
            "podlove": SimpleUploadedFile("upload.json", json.dumps(podlove).encode()),
            "dote": SimpleUploadedFile("upload.dote.json", json.dumps(DOTE).encode()),
            "vtt": SimpleUploadedFile("upload.vtt", VTT.encode()),
        }

        response = admin_client.post(
            reverse("cast-transcript:edit", args=(received_transcript.pk,)),
            {"audio": received_transcript.audio_id, **uploads},
        )

        assert response.status_code == 302
        transcript = Transcript.objects.get(pk=received_transcript.pk)
        assert transcript.podlove_data["transcripts"][0]["text"] == "uploaded"
        assert transcript.source_fingerprint != source_fingerprint
        assert transcript.source_fingerprint == transcript.transcript_artifact_fingerprint()
        assert_stale(transcript, mapping)

    def test_admin_upload_of_podlove_only_keeps_the_stored_dote_and_webvtt(self, admin_client, received_transcript):
        mapping = approve(received_transcript, "Speaker 1", "Alice")
        dote_name, vtt_name = received_transcript.dote.name, received_transcript.vtt.name
        podlove = json.loads(json.dumps(PODLOVE))
        podlove["transcripts"][0]["text"] = "uploaded"

        response = admin_client.post(
            reverse("cast-transcript:edit", args=(received_transcript.pk,)),
            {
                "audio": received_transcript.audio_id,
                "podlove": SimpleUploadedFile("upload.json", json.dumps(podlove).encode()),
            },
        )

        assert response.status_code == 302
        transcript = Transcript.objects.get(pk=received_transcript.pk)
        assert transcript.podlove_data["transcripts"][0]["text"] == "uploaded"
        assert (transcript.dote.name, transcript.vtt.name) == (dote_name, vtt_name)
        assert transcript.dote_data == DOTE
        assert transcript.source_fingerprint == transcript.transcript_artifact_fingerprint()
        assert_stale(transcript, mapping)

    def test_partial_save_of_an_older_instance_hashes_the_stored_artifacts(self, received_transcript):
        older = Transcript.objects.get(pk=received_transcript.pk)
        newer = Transcript.objects.get(pk=received_transcript.pk)
        newer.podlove.save("newer.json", ContentFile(b'{"transcripts": []}'), save=False)
        newer.save(update_fields=["podlove"])
        newer_fingerprint = Transcript.objects.get(pk=received_transcript.pk).source_fingerprint

        older.vtt.save("older.vtt", ContentFile(b"WEBVTT\n"), save=False)
        older.save(update_fields=["vtt"])

        transcript = Transcript.objects.get(pk=received_transcript.pk)
        assert transcript.podlove.name == newer.podlove.name
        assert transcript.source_fingerprint not in ("", newer_fingerprint, received_transcript.source_fingerprint)
        assert transcript.source_fingerprint == transcript.transcript_artifact_fingerprint()
        assert older.source_fingerprint == transcript.source_fingerprint

    def test_failed_fingerprint_rolls_back_the_artifact_save(self, received_transcript, monkeypatch):
        transcript = Transcript.objects.get(pk=received_transcript.pk)
        stored_name = transcript.podlove.name
        transcript.podlove.save("failing.json", ContentFile(b'{"transcripts": []}'), save=False)

        def fail(self):
            raise OSError("unreadable")

        monkeypatch.setattr(Transcript, "transcript_artifact_fingerprint", fail)
        with pytest.raises(OSError):
            transcript.save(update_fields=["podlove"])

        stored = Transcript.objects.get(pk=received_transcript.pk)
        assert stored.podlove.name == stored_name
        assert stored.source_fingerprint == received_transcript.source_fingerprint

    @pytest.mark.parametrize("save", [Transcript.save, save_transcript_with_derivations])
    def test_update_fields_iterator_is_consumed_once(self, received_transcript, save):
        transcript = Transcript.objects.get(pk=received_transcript.pk)
        transcript.podlove.save("iterated.json", ContentFile(b'{"transcripts": []}'), save=False)

        save(transcript, update_fields=(name for name in ["podlove"]))

        stored = Transcript.objects.get(pk=received_transcript.pk)
        assert stored.podlove.name == transcript.podlove.name
        assert stored.source_fingerprint == stored.transcript_artifact_fingerprint()

    def test_tracking_uses_the_write_alias_of_the_save(self, received_transcript, mocker):
        transcript = Transcript.objects.get(pk=received_transcript.pk)
        transcript._state.db = "unconfigured-alias"
        mocker.patch("cast.models.transcript.router.db_for_write", return_value="default")
        transcript.podlove.save("routed.json", ContentFile(b'{"transcripts": []}'), save=False)

        transcript.save(update_fields=["podlove"])

        stored = Transcript.objects.get(pk=received_transcript.pk)
        assert stored.podlove.name == transcript.podlove.name
        assert stored.source_fingerprint == stored.transcript_artifact_fingerprint() != ""

    @pytest.mark.skipif(DJANGO_VERSION >= (6, 0), reason="Django 6 rejects positional save arguments")
    @pytest.mark.filterwarnings("ignore:Passing positional arguments to save")
    def test_positional_save_arguments_are_tracked(self, received_transcript):
        transcript = Transcript.objects.get(pk=received_transcript.pk)
        transcript.podlove.save("positional.json", ContentFile(b'{"transcripts": []}'), save=False)

        transcript.save(False, False, "default", ["podlove"])

        stored = Transcript.objects.get(pk=received_transcript.pk)
        assert stored.podlove.name == transcript.podlove.name
        assert stored.source_fingerprint == stored.transcript_artifact_fingerprint()
        assert stored.source_fingerprint != received_transcript.source_fingerprint

    @pytest.mark.skipif(DJANGO_VERSION < (6, 0), reason="Django < 6 accepts positional save arguments")
    def test_positional_save_arguments_are_rejected_on_django_6(self, received_transcript):
        transcript = Transcript.objects.get(pk=received_transcript.pk)

        with pytest.raises(TypeError, match="takes 1 positional argument"):
            transcript.save(False, False, "default", ["podlove"])

    def test_saving_a_deleted_row_records_artifacts_again(self, received_transcript):
        Transcript.objects.filter(pk=received_transcript.pk).update(source_fingerprint="")
        Transcript.objects.filter(pk=received_transcript.pk).delete()
        received_transcript.source_fingerprint = ""

        received_transcript.save()

        transcript = Transcript.objects.get(pk=received_transcript.pk)
        assert transcript.source_fingerprint == transcript.transcript_artifact_fingerprint() != ""

    def test_migration_sets_fingerprint_of_existing_rows(self, received_transcript):
        migration = importlib.import_module("cast.migrations.0084_transcript_source_fingerprint")
        expected = received_transcript.transcript_artifact_fingerprint()
        empty = create_transcript()
        missing = create_transcript(podlove={"transcripts": []})
        missing.podlove.storage.delete(missing.podlove.name)
        Transcript.objects.update(source_fingerprint="")

        migration.set_source_fingerprints(apps, SimpleNamespace(connection=connection))

        assert Transcript.objects.get(pk=received_transcript.pk).source_fingerprint == expected
        assert Transcript.objects.get(pk=empty.pk).source_fingerprint == ""
        assert Transcript.objects.get(pk=missing.pk).source_fingerprint == ""
