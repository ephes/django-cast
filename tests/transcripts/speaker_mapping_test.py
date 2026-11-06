import json
import re

import pytest
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction

from cast.devdata import create_transcript
from cast.media_derivation import save_transcript_with_derivations
from cast.models import Contributor, Transcript, TranscriptSpeakerMapping
from cast.transcript_sanitization import sanitize_webvtt_content
from cast.transcripts import parsing, speaker_samples, webvtt


class TestTranscriptSpeakerMapping:
    pytestmark = pytest.mark.django_db

    def test_get_speaker_labels_from_podlove_and_dote(self, audio):
        transcript = create_transcript(
            audio=audio,
            podlove={
                "transcripts": [
                    {"speaker": "Speaker 2", "voice": "Speaker 1", "text": "Hello"},
                    {"speaker": "", "voice": None, "text": "empty"},
                    "not an object",
                ]
            },
            dote={
                "lines": [
                    {"speakerDesignation": "Speaker 3", "text": "Hi"},
                    {"speakerDesignation": "  ", "text": "blank"},
                    "not an object",
                ]
            },
        )

        assert transcript.get_speaker_labels() == ["Speaker 1", "Speaker 2", "Speaker 3"]

    def test_speaker_mapping_rows_are_created_from_unique_nonblank_labels(self, audio):
        transcript = create_transcript(
            audio=audio,
            podlove={
                "transcripts": [
                    {"speaker": " Speaker 1 ", "voice": "Speaker 1", "text": "Hello"},
                    {"speaker": "", "voice": None, "text": "empty"},
                ]
            },
            dote={
                "lines": [
                    {"speakerDesignation": "Speaker 2", "text": "Hi"},
                    {"speakerDesignation": "  ", "text": "blank"},
                ]
            },
            vtt=(
                "WEBVTT\n\n"
                "00:00:00.000 --> 00:00:01.000\n"
                "<v Speaker 3>Voice label</v>\n\n"
                "00:00:01.000 --> 00:00:02.000\n"
                "Speaker 4: Generic prefix\n\n"
                "00:00:02.000 --> 00:00:03.000\n"
                "<v >Blank voice label</v>\n"
            ),
        )

        mappings = list(transcript.speaker_mappings.order_by("speaker_label"))

        assert [mapping.speaker_label for mapping in mappings] == [
            "Speaker 1",
            "Speaker 2",
            "Speaker 3",
            "Speaker 4",
        ]
        assert {mapping.review_state for mapping in mappings} == {TranscriptSpeakerMapping.ReviewState.UNMAPPED}
        assert all(mapping.active for mapping in mappings)
        assert all(
            mapping.source_artifact_fingerprint == transcript.transcript_artifact_fingerprint() for mapping in mappings
        )

    def test_transcript_artifact_fingerprint_stays_stable_after_s3_style_prior_reads(
        self, audio, s3_style_fieldfile_reopen_guard
    ):
        transcript = create_transcript(
            audio=audio,
            podlove={"transcripts": [{"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Hello"}]},
            dote={"lines": [{"speakerDesignation": "Speaker 2", "text": "Hi"}]},
            vtt=("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n<v Speaker 3>WebVTT speaker</v>\n"),
        )
        expected_fingerprint = transcript.transcript_artifact_fingerprint()
        s3_style_fieldfile_reopen_guard()

        assert transcript.podlove_data["transcripts"][0]["speaker"] == "Speaker 1"
        assert transcript.dote_data["lines"][0]["speakerDesignation"] == "Speaker 2"
        assert "Speaker 3" in transcript._load_text_file("vtt")
        assert transcript.get_speaker_labels() == ["Speaker 1", "Speaker 2", "Speaker 3"]
        assert transcript.transcript_artifact_fingerprint() == expected_fingerprint

    def test_speaker_mapping_uniqueness_is_per_transcript_label(self, audio):
        transcript = create_transcript(audio=audio, podlove={"transcripts": [{"speaker": "Speaker 1"}]})
        other_transcript = create_transcript(podlove={"transcripts": [{"speaker": "Speaker 1"}]})

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                TranscriptSpeakerMapping.objects.create(transcript=transcript, speaker_label="Speaker 1")

        assert other_transcript.speaker_mappings.filter(speaker_label="Speaker 1").count() == 1

    def test_approved_speaker_mapping_validation_requires_one_target(self, audio):
        transcript = create_transcript(audio=audio, podlove={"transcripts": [{"speaker": "Speaker 1"}]})
        mapping = transcript.speaker_mappings.get(speaker_label="Speaker 1")
        assert str(mapping) == f"{transcript.pk}: Speaker 1"
        assert mapping.target_display_name == ""
        assert not mapping.is_current_for_fingerprint(transcript.transcript_artifact_fingerprint())
        mapping.review_state = TranscriptSpeakerMapping.ReviewState.APPROVED

        with pytest.raises(ValidationError):
            mapping.full_clean()

        contributor = Contributor.objects.create(display_name="Alice", slug="alice")
        mapping.contributor = contributor
        mapping.display_name = "One-off Alice"
        with pytest.raises(ValidationError):
            mapping.full_clean()

        mapping.display_name = ""
        mapping.full_clean()
        mapping.source_artifact_fingerprint = transcript.transcript_artifact_fingerprint()
        assert mapping.target_display_name == "Alice"
        assert mapping.is_current_for_fingerprint(transcript.transcript_artifact_fingerprint())

    def test_speaker_mapping_sync_marks_replaced_artifacts_stale_inactive_and_unmapped(self, audio):
        contributor = Contributor.objects.create(display_name="Alice", slug="alice")
        transcript = create_transcript(
            audio=audio,
            podlove={
                "transcripts": [
                    {"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Hello"},
                    {"speaker": "Speaker 2", "voice": "Speaker 2", "text": "Still unmapped"},
                    {"speaker": "Speaker 3", "voice": "Speaker 3", "text": "Gone"},
                ]
            },
        )
        for speaker_label in ("Speaker 1", "Speaker 3"):
            mapping = transcript.speaker_mappings.get(speaker_label=speaker_label)
            mapping.contributor = contributor
            mapping.review_state = TranscriptSpeakerMapping.ReviewState.APPROVED
            mapping.source_artifact_fingerprint = transcript.transcript_artifact_fingerprint()
            mapping.save()

        replacement = json.dumps(
            {
                "transcripts": [
                    {"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Still here"},
                    {"speaker": "Speaker 2", "voice": "Speaker 2", "text": "Still unmapped"},
                    {"speaker": "Speaker 4", "voice": "Speaker 4", "text": "New"},
                ]
            }
        ).encode("utf-8")
        transcript.podlove.save("replacement.json", ContentFile(replacement), save=False)
        save_transcript_with_derivations(transcript)

        mappings = {mapping.speaker_label: mapping for mapping in transcript.speaker_mappings.all()}
        assert mappings["Speaker 1"].active
        assert mappings["Speaker 1"].review_state == TranscriptSpeakerMapping.ReviewState.STALE
        assert mappings["Speaker 2"].active
        assert mappings["Speaker 2"].source_artifact_fingerprint == transcript.transcript_artifact_fingerprint()
        assert not mappings["Speaker 3"].active
        assert mappings["Speaker 3"].review_state == TranscriptSpeakerMapping.ReviewState.STALE
        assert mappings["Speaker 4"].active
        assert mappings["Speaker 4"].review_state == TranscriptSpeakerMapping.ReviewState.UNMAPPED

        reappearing = json.dumps({"transcripts": [{"speaker": "Speaker 3", "voice": "Speaker 3", "text": "Back"}]})
        transcript.podlove.save("reappearing.json", ContentFile(reappearing.encode("utf-8")), save=False)
        save_transcript_with_derivations(transcript)

        mappings = {mapping.speaker_label: mapping for mapping in transcript.speaker_mappings.all()}
        assert mappings["Speaker 3"].active
        assert mappings["Speaker 3"].review_state == TranscriptSpeakerMapping.ReviewState.STALE

    def test_speaker_mapping_sync_handles_unchanged_and_already_inactive_rows(self, audio, mocker):
        transcript = create_transcript(audio=audio, podlove={"transcripts": [{"speaker": "Speaker 1"}]})
        mapping = transcript.speaker_mappings.get(speaker_label="Speaker 1")
        mapping.source_artifact_fingerprint = transcript.transcript_artifact_fingerprint()
        mapping.save(update_fields=["source_artifact_fingerprint"])
        mocker.patch("cast.transcripts.services.timezone.now", return_value=mapping.last_seen)

        transcript.sync_speaker_mappings()

        transcript.podlove.save("empty.json", ContentFile(b'{"transcripts": []}'), save=False)
        save_transcript_with_derivations(transcript)
        inactive_mapping = transcript.speaker_mappings.get(speaker_label="Speaker 1")
        assert not inactive_mapping.active

        transcript.sync_speaker_mappings()

    def test_sync_speaker_mappings_ignores_unsaved_transcripts(self):
        transcript = Transcript()

        transcript.sync_speaker_mappings()

    def test_get_webvtt_speaker_labels_ignores_blank_voice_labels(self):
        content = (
            "WEBVTT\n\n"
            "00:00:00.000 --> 00:00:01.000\n"
            "<v >Blank</v>\n"
            "<v>No voice label</v>\n"
            "<v.loud Speaker 1>Classed voice label</v>\n"
        )

        assert webvtt.get_speaker_labels(content) == {"Speaker 1"}

    def test_speaker_mapping_sync_marks_approved_row_with_deleted_contributor_stale(self, audio):
        contributor = Contributor.objects.create(display_name="Deleted Alice", slug="deleted-alice")
        transcript = create_transcript(audio=audio, podlove={"transcripts": [{"speaker": "Speaker 1"}]})
        mapping = transcript.speaker_mappings.get(speaker_label="Speaker 1")
        mapping.contributor = contributor
        mapping.review_state = TranscriptSpeakerMapping.ReviewState.APPROVED
        mapping.source_artifact_fingerprint = transcript.transcript_artifact_fingerprint()
        mapping.save()
        contributor.delete()

        transcript.sync_speaker_mappings()

        mapping.refresh_from_db()
        assert mapping.contributor_id is None
        assert mapping.review_state == TranscriptSpeakerMapping.ReviewState.STALE

    def test_get_speaker_labels_handles_missing_and_invalid_files(self, audio):
        transcript = create_transcript(audio=audio)
        assert transcript.get_speaker_labels() == []

        transcript.podlove.name = "cast_transcript/missing-podlove.json"
        transcript.dote.save("invalid-dote.json", ContentFile("not json"))
        transcript.save()
        assert transcript.get_speaker_labels() == []

        transcript.podlove.save("list-podlove.json", ContentFile("[]"))
        transcript.dote.name = "cast_transcript/missing-dote.json"
        transcript.save()
        assert transcript.get_speaker_labels() == []

    def test_speaker_labels_samples_and_rewrite_strip_label_whitespace(self, audio):
        transcript = create_transcript(
            audio=audio,
            podlove={
                "transcripts": [
                    {
                        "speaker": " Speaker 1 ",
                        "voice": " Speaker 1 ",
                        "start": "00:00:01.500",
                        "text": "This sample sentence has enough content to identify speaker one.",
                    }
                ]
            },
            dote={
                "lines": [
                    {
                        "speakerDesignation": " Speaker 2 ",
                        "startTime": "00:00:02,500",
                        "text": "This sample sentence has enough content to identify speaker two.",
                    }
                ]
            },
        )

        assert transcript.get_speaker_labels() == ["Speaker 1", "Speaker 2"]
        samples = transcript.get_speaker_samples()
        assert sorted(samples.keys()) == ["Speaker 1", "Speaker 2"]

        assert transcript.rewrite_speaker_labels({"Speaker 1": "Alice", "Speaker 2": "Bob"})

        with transcript.podlove.open("r") as podlove_file:
            podlove_data = json.load(podlove_file)
        with transcript.dote.open("r") as dote_file:
            dote_data = json.load(dote_file)
        assert podlove_data["transcripts"][0]["speaker"] == "Alice"
        assert podlove_data["transcripts"][0]["voice"] == "Alice"
        assert dote_data["lines"][0]["speakerDesignation"] == "Bob"

    def test_get_speaker_samples_spreads_useful_podlove_samples(self, audio):
        transcript = create_transcript(
            audio=audio,
            podlove={
                "transcripts": [
                    "not an object",
                    {"speaker": "", "text": "No speaker label here"},
                    {"speaker": "Speaker 1", "text": None},
                    {"speaker": "Speaker 1", "start_ms": 620, "text": "ja"},
                    {
                        "speaker": "Speaker 1",
                        "start_ms": 10_000,
                        "text": "First substantial sentence from speaker one that is long enough to be useful.",
                    },
                    {
                        "speaker": "Speaker 1",
                        "start": "00:05:00.000",
                        "text": "Second substantial sentence from speaker one that helps identify the voice.",
                    },
                    {
                        "speaker": "Speaker 1",
                        "startTime": 900,
                        "text": "Third substantial sentence from speaker one with useful identifying content.",
                    },
                    {
                        "speaker": "Speaker 1",
                        "start": "00:20:00.000",
                        "text": "Fourth substantial sentence from speaker one near the end of the episode.",
                    },
                    {
                        "voice": "Voice 1",
                        "text": "Voice only segment has enough words to become a transcript sample.",
                    },
                ]
            },
        )

        samples = transcript.get_speaker_samples(max_chars=48)

        assert [sample.timestamp_label for sample in samples["Speaker 1"]] == ["00:10", "15:00", "20:00"]
        assert samples["Speaker 1"][0].text == "First substantial sentence from speaker one..."
        assert samples["Speaker 1"][0].start_seconds == 10
        assert samples["Speaker 1"][0].has_start_time
        assert [sample.text for sample in samples["Speaker 1"]] == [
            "First substantial sentence from speaker one...",
            "Third substantial sentence from speaker one...",
            "Fourth substantial sentence from speaker one...",
        ]
        assert samples["Voice 1"][0].timestamp_label == ""
        assert samples["Voice 1"][0].start_seconds is None
        assert not samples["Voice 1"][0].has_start_time
        assert transcript.get_speaker_samples(limit=1)["Speaker 1"][0].timestamp_label == "00:10"
        assert transcript.get_speaker_samples(limit=0) == {}
        # The pure module API keeps its own guard even though the service guards first.
        assert speaker_samples.get_speaker_samples({}, {}, limit=0) == {}

    def test_get_speaker_samples_uses_dote_fallback_and_low_signal_fallback(self, audio):
        low_signal_text = "ja ja ja ja ja ja ja ja ja ja ja ja ja ja ja ja"
        transcript = create_transcript(
            audio=audio,
            podlove={
                "transcripts": [
                    {"speaker": "Speaker 2", "start": "00:00:00.000", "text": low_signal_text},
                    {"speaker": "Speaker 3", "start": "00:00:02.000", "text": low_signal_text},
                ]
            },
            dote={
                "lines": [
                    "not an object",
                    {"speakerDesignation": "", "text": "Missing speaker"},
                    {"speakerDesignation": "Speaker 4", "text": None},
                    {
                        "speakerDesignation": "Speaker 2",
                        "startTime": "00:00:01,500",
                        "text": "DOTe fallback has a longer sentence with enough identifying words.",
                    },
                    {
                        "speakerDesignation": "Hour Speaker",
                        "startTime": "01:02:03,900",
                        "text": "Hour timestamp sentence has enough useful identifying transcript content.",
                    },
                ]
            },
        )

        samples = transcript.get_speaker_samples()

        assert samples["Speaker 2"][0].text == "DOTe fallback has a longer sentence with enough identifying words."
        assert samples["Speaker 2"][0].timestamp_label == "00:01"
        assert samples["Speaker 2"][0].start_seconds == 1.5
        assert samples["Speaker 3"][0].text == low_signal_text
        assert samples["Hour Speaker"][0].timestamp_label == "01:02:03"

    def test_speaker_sample_helpers_handle_edge_cases(self):
        assert parsing.parse_timestamp_seconds(True) is None
        assert parsing.parse_timestamp_seconds(None) is None
        assert parsing.parse_timestamp_seconds("") is None
        assert parsing.parse_timestamp_seconds("not a timestamp") is None
        assert parsing.parse_timestamp_seconds("00:00:not-a-number") is None
        assert parsing.parse_timestamp_seconds("00:00:00:00") is None
        assert parsing.parse_timestamp_seconds(-1) is None
        assert parsing.parse_timestamp_seconds("-1") is None
        assert parsing.parse_timestamp_seconds("65.5") == 65.5
        assert parsing.parse_timestamp_seconds("01:02") == 62
        assert (
            parsing.parse_record_start_seconds(
                {"start_ms": False, "start": "00:00:02"},
                timestamp_fields=("start",),
            )
            == 2
        )
        assert parsing.parse_record_start_seconds({"start_ms": -1}, timestamp_fields=("start",)) is None
        assert parsing.format_sample_timestamp(None) == ""

        assert parsing.clean_sample_text(5) == ""
        assert not parsing.sample_text_is_useful("short", min_chars=10, min_words=1)
        assert not parsing.sample_text_is_useful("one two three", min_chars=1, min_words=4)
        assert not parsing.sample_text_is_useful("okay", min_chars=1, min_words=1)
        assert not parsing.sample_text_is_useful("mhm mhm mhm mhm", min_chars=1, min_words=4)
        assert parsing.sample_text_is_useful("你好 你好 你好 你好", min_chars=1, min_words=4)

    def test_rewrite_speaker_labels_updates_podlove_dote_and_vtt_voice_labels(self, audio):
        vtt = (
            "WEBVTT\r\n\r\n"
            "00:00:00.000 --> 00:00:01.000\r\n"
            "<v Speaker 1>Hello from speaker one</v>\r\n\r\n"
            "00:00:01.000 --> 00:00:02.000\n"
            "<v Speaker 1>Opening-only voice tag\n\n"
            "00:00:02.000 --> 00:00:03.000\n"
            "<v Speaker 3>Unmapped voice</v>\n"
            "Speaker 1 remains cue text\n"
        )
        transcript = create_transcript(
            audio=audio,
            podlove={
                "transcripts": [
                    {"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Hello"},
                    {"speaker": "Speaker 2", "voice": "Other", "text": "Hi"},
                    "not an object",
                ]
            },
            dote={
                "lines": [
                    {"speakerDesignation": "Speaker 2", "text": "Hi"},
                    {"speakerDesignation": None, "text": "No speaker"},
                    "not an object",
                ]
            },
            vtt=vtt,
        )

        assert transcript.rewrite_speaker_labels({"Speaker 1": "Alice", "Speaker 2": "Bob"})

        with transcript.podlove.open("r") as podlove_file:
            podlove_data = json.load(podlove_file)
        with transcript.dote.open("r") as dote_file:
            dote_data = json.load(dote_file)
        with transcript.vtt.open("rb") as vtt_file:
            vtt_content = vtt_file.read().decode("utf-8")
        assert podlove_data["transcripts"][0]["speaker"] == "Alice"
        assert podlove_data["transcripts"][0]["voice"] == "Alice"
        assert podlove_data["transcripts"][1]["speaker"] == "Bob"
        assert podlove_data["transcripts"][1]["voice"] == "Other"
        assert dote_data["lines"][0]["speakerDesignation"] == "Bob"
        assert vtt_content == (
            "WEBVTT\r\n\r\n"
            "00:00:00.000 --> 00:00:01.000\r\n"
            "<v Alice>Hello from speaker one</v>\r\n\r\n"
            "00:00:01.000 --> 00:00:02.000\n"
            "<v Alice>Opening-only voice tag\n\n"
            "00:00:02.000 --> 00:00:03.000\n"
            "<v Speaker 3>Unmapped voice</v>\n"
            "Speaker 1 remains cue text\n"
        )

    def test_rewrite_speaker_labels_updates_vtt_generic_speaker_prefixes(self, audio):
        vtt = (
            "WEBVTT\r\n\r\n"
            "00:00:00.000 --> 00:00:01.000\r\n"
            "Speaker 1: Hello from the prefix\r\n\r\n"
            "00:00:01.000 --> 00:00:02.000\n"
            "  speaker 2 :  Indented, lower-case prefix\n\n"
            "00:00:02.000 --> 00:00:03.000\n"
            "Speaker 3: Unmapped prefix\n"
            "Not a prefix: Speaker 1: stays\n\n"
            "NOTE Speaker 1: outside a cue payload\n"
        )
        transcript = create_transcript(
            audio=audio,
            podlove={"transcripts": [{"speaker": "Speaker 1", "text": "Hello"}]},
            vtt=vtt,
        )
        assert transcript.get_speaker_labels() == ["Speaker 1", "Speaker 3", "speaker 2"]

        assert transcript.rewrite_speaker_labels({"Speaker 1": "Alice", "speaker 2": "Bob"})

        with transcript.vtt.open("rb") as vtt_file:
            vtt_content = vtt_file.read().decode("utf-8")
        assert vtt_content == (
            "WEBVTT\r\n\r\n"
            "00:00:00.000 --> 00:00:01.000\r\n"
            "<v Alice>Alice: Hello from the prefix</v>\r\n\r\n"
            "00:00:01.000 --> 00:00:02.000\n"
            "  <v Bob>Bob: Indented, lower-case prefix</v>\n\n"
            "00:00:02.000 --> 00:00:03.000\n"
            "Speaker 3: Unmapped prefix\n"
            "Not a prefix: Speaker 1: stays\n\n"
            "NOTE Speaker 1: outside a cue payload\n"
        )
        assert transcript.get_speaker_labels() == ["Alice", "Bob", "Speaker 3"]

        assert transcript.rewrite_speaker_labels({"Alice": "Carol"})

        with transcript.vtt.open("rb") as vtt_file:
            vtt_content = vtt_file.read().decode("utf-8")
        assert "<v Carol>Carol: Hello from the prefix</v>\r\n" in vtt_content
        assert "Alice" not in vtt_content
        assert transcript.get_speaker_labels() == ["Bob", "Carol", "Speaker 3"]
        sanitized = sanitize_webvtt_content(vtt_content, {"Bob"})
        assert "00:00:00.000 --> 00:00:01.000\r\nHello from the prefix\r\n" in sanitized
        assert "Carol" not in sanitized
        assert "  <v Bob>Bob: Indented, lower-case prefix</v>\n" in sanitized

    def test_webvtt_rewrite_closes_renamed_prefixes_per_line(self):
        cue = "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n"
        content = f"{cue}Speaker 1: first\nSpeaker 2: second\nSpeaker 1: third\n"

        rewritten, changed = webvtt.rewrite_speakers(content, {"Speaker 1": "Alice", "Speaker 2": "Bob"})

        assert changed
        assert rewritten == (f"{cue}<v Alice>Alice: first</v>\n<v Bob>Bob: second</v>\n<v Alice>Alice: third</v>\n")
        assert webvtt.get_speaker_labels(rewritten) == {"Alice", "Bob"}

        renamed_again, changed = webvtt.rewrite_speakers(rewritten, {"Alice": "Carol"})

        assert changed
        assert renamed_again == (
            f"{cue}<v Carol>Carol: first</v>\n<v Bob>Bob: second</v>\n<v Carol>Carol: third</v>\n"
        )
        assert sanitize_webvtt_content(renamed_again, {"Bob"}) == f"{cue}first\n<v Bob>Bob: second</v>\nthird\n"
        assert sanitize_webvtt_content(renamed_again, {"Carol"}) == (
            f"{cue}<v Carol>Carol: first</v>\nsecond\n<v Carol>Carol: third</v>\n"
        )

    def test_webvtt_suggestions_replace_or_drop_echoed_prefix_labels(self):
        cue = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n"
        renamed, _changed = webvtt.rewrite_speakers(f"{cue}Speaker 1: hello\nSpeaker 1:\n", {"Speaker 1": "Alice"})
        assert renamed == f"{cue}<v Alice>Alice: hello</v>\n<v Alice>Alice: </v>\n"

        applied, applied_count, changed = webvtt.apply_suggestions_to_content(renamed, {1000: "Bob"})

        assert (applied_count, changed) == (1, True)
        assert applied == f"{cue}<v Bob>Bob: hello</v>\n<v Bob>Bob: </v>\n"
        assert webvtt.get_speaker_labels(applied) == {"Bob"}
        assert sanitize_webvtt_content(applied, set()) == f"{cue}hello\n\n"

        cleared, cleared_count, changed = webvtt.clear_suggestions_from_content(renamed, {1000})

        assert (cleared_count, changed) == (1, True)
        assert cleared == f"{cue}hello\n"
        assert webvtt.get_speaker_labels(cleared) == set()

    def test_webvtt_suggestions_treat_unrenamed_generic_prefixes_like_a_rename(self):
        cue = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n"
        content = f"{cue}Speaker 1: hi\r\n  speaker 2 :  indented\nplain continuation\n"

        applied, applied_count, changed = webvtt.apply_suggestions_to_content(content, {1000: "Bob"})

        assert (applied_count, changed) == (1, True)
        assert applied == (f"{cue}<v Bob>Bob: hi</v>\r\n  <v Bob>Bob: indented</v>\nplain continuation\n")
        assert "Speaker" not in applied
        assert webvtt.get_speaker_labels(applied) == {"Bob"}
        assert sanitize_webvtt_content(applied, set()) == f"{cue}hi\r\n  indented\nplain continuation\n"
        assert sanitize_webvtt_content(applied, {"Bob"}) == applied

        reapplied, _count, changed = webvtt.apply_suggestions_to_content(applied, {1000: "Carol"})

        assert changed
        assert reapplied == applied.replace("Bob", "Carol")

        cleared, cleared_count, changed = webvtt.clear_suggestions_from_content(content, {1000})

        assert (cleared_count, changed) == (1, True)
        assert cleared == f"{cue}hi\r\n  indented\nplain continuation\n"
        assert webvtt.get_speaker_labels(cleared) == set()
        assert webvtt.clear_suggestions_from_content(applied, {1000})[0] == cleared

        label_only = f"{cue}Speaker 1:\nmore text\n\n00:00:02.000 --> 00:00:03.000\nSpeaker 2:\n"
        cleared, cleared_count, changed = webvtt.clear_suggestions_from_content(label_only, {1000, 2000})
        assert (cleared_count, changed) == (2, True)
        assert cleared == f"{cue}more text\n\n00:00:02.000 --> 00:00:03.000\n"

        later_prefix = f"{cue}plain first\nSpeaker 1: second\n"
        assert webvtt.apply_suggestions_to_content(later_prefix, {1000: "Bob"})[0] == (
            f"{cue}<v Bob>plain first\n<v Bob>Bob: second</v>\n"
        )

        nested = f"{cue}Speaker 3: inner <v Speaker 4>voice</v>\n"
        assert webvtt.apply_suggestions_to_content(nested, {1000: "Bob"})[0] == (
            f"{cue}<v Bob>Bob: inner <v Bob>voice</v></v>\n"
        )
        assert webvtt.clear_suggestions_from_content(nested, {1000})[0] == f"{cue}inner voice\n"

    def test_webvtt_suggestions_only_touch_matching_cues_with_generic_prefixes(self):
        content = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:02.000\n"
            "Speaker 1: matched\n\n"
            "00:00:02.000 --> 00:00:03.000\n"
            "Speaker 1: other cue\n\n"
            "00:00:03.000 --> 00:00:04.000\n"
            "Not a prefix: Speaker 1: stays\n"
        )

        applied, applied_count, _changed = webvtt.apply_suggestions_to_content(content, {1000: "Bob", 3000: "Eve"})

        assert applied_count == 2
        assert applied == (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:02.000\n"
            "<v Bob>Bob: matched</v>\n\n"
            "00:00:02.000 --> 00:00:03.000\n"
            "Speaker 1: other cue\n\n"
            "00:00:03.000 --> 00:00:04.000\n"
            "<v Eve>Not a prefix: Speaker 1: stays\n"
        )

        cleared, cleared_count, _changed = webvtt.clear_suggestions_from_content(content, {1000, 3000})

        assert cleared_count == 2
        assert "00:00:01.000 --> 00:00:02.000\nmatched\n" in cleared
        assert "Speaker 1: other cue\n" in cleared
        assert "Not a prefix: Speaker 1: stays\n" in cleared

    def test_webvtt_echoed_label_rewrite_edge_cases(self):
        cue = "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n"
        content = (
            f"{cue}<v.loud Dr: Who>Dr: Who :  opening only\n"
            "<v Bob>Alice: not an echo</v>\n"
            "<v Alice>Alice no separator</v>\n"
            "<v Alice>Alice: inner <v Speaker 2>voice</v>\n"
            "<v>no label\n"
            "Speaker 9: unmapped <v Speaker 2>inner</v>\n"
            "Speaker 1: mapped <v Speaker 2>inner</v>\n"
        )

        rewritten, changed = webvtt.rewrite_speakers(
            content, {"Dr: Who": "Eve", "Alice": "Carol", "Speaker 1": "Ann", "Speaker 2": "Zed"}
        )

        assert changed
        assert rewritten == (
            f"{cue}<v.loud Eve>Eve: opening only\n"
            "<v Bob>Alice: not an echo</v>\n"
            "<v Carol>Alice no separator</v>\n"
            "<v Carol>Carol: inner <v Zed>voice</v>\n"
            "<v>no label\n"
            "Speaker 9: unmapped <v Zed>inner</v>\n"
            "<v Ann>Ann: mapped <v Zed>inner</v></v>\n"
        )
        assert sanitize_webvtt_content(f"{cue}<v Alice>Alice: hidden</v>\n<v Bob>Bob: kept\n", {"Bob"}) == (
            f"{cue}hidden\n<v Bob>Bob: kept\n"
        )

    @pytest.mark.parametrize(
        "payload",
        [
            "<v Speaker 1>Voice span</v>",
            "<v.loud Speaker 1>Classed voice span</v>",
            "<v Speaker 1>Opening-only voice",
            "Speaker 1: Generic prefix",
            "   speaker 1:Indented lower-case prefix",
            "Speaker 1 : <v Speaker 2>Prefix and voice</v>",
        ],
    )
    def test_webvtt_speaker_labels_match_what_rewrite_can_rename(self, payload):
        content = f"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n{payload}\n"
        labels = webvtt.get_speaker_labels(content)
        assert labels

        renamed = {label: f"Renamed {index}" for index, label in enumerate(sorted(labels))}
        rewritten, changed = webvtt.rewrite_speakers(content, renamed)

        assert changed
        for label in labels:
            assert webvtt.rewrite_speakers(content, {label: "Renamed"})[1], label
        assert webvtt.get_speaker_labels(rewritten).isdisjoint(labels)

    def test_rewrite_speaker_labels_saves_when_only_vtt_changes(self, audio, django_capture_on_commit_callbacks):
        transcript = create_transcript(
            audio=audio,
            vtt="WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n<v Speaker 1>Only WebVTT\n",
        )
        original_vtt_name = transcript.vtt.name

        with django_capture_on_commit_callbacks(execute=True):
            assert transcript.rewrite_speaker_labels({"Speaker 1": "Alice"})

        transcript.refresh_from_db()
        assert transcript.vtt.name != original_vtt_name
        assert not transcript.vtt.storage.exists(original_vtt_name)
        with transcript.vtt.open("r") as vtt_file:
            assert vtt_file.read() == "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n<v Alice>Only WebVTT\n"

    def test_rewrite_speaker_labels_replaces_generated_suffix_instead_of_accumulating_it(self, audio):
        transcript = Transcript.objects.create(audio=audio)
        base_name = f"repeat-safe-{transcript.pk}"
        transcript.podlove.save(
            f"{base_name}.podlove.json",
            ContentFile(json.dumps({"transcripts": [{"speaker": "Speaker 1", "voice": "Speaker 1"}]})),
            save=False,
        )
        transcript.dote.save(
            f"{base_name}.dote.json",
            ContentFile(json.dumps({"lines": [{"speakerDesignation": "Speaker 2"}]})),
            save=False,
        )
        transcript.save()

        assert transcript.rewrite_speaker_labels({"Speaker 1": "Alice", "Speaker 2": "Bob"})
        transcript.refresh_from_db()
        assert transcript.rewrite_speaker_labels({"Alice": "Carol", "Bob": "Dana"})
        transcript.refresh_from_db()

        podlove_name = transcript.podlove.name.rsplit("/", 1)[-1]
        dote_name = transcript.dote.name.rsplit("/", 1)[-1]
        assert re.fullmatch(rf"{base_name}-[0-9a-f]{{12}}\.podlove\.json", podlove_name)
        assert re.fullmatch(rf"{base_name}-[0-9a-f]{{12}}\.dote\.json", dote_name)
        with transcript.podlove.open("r") as podlove_file:
            assert json.load(podlove_file)["transcripts"][0]["speaker"] == "Carol"
        with transcript.dote.open("r") as dote_file:
            assert json.load(dote_file)["lines"][0]["speakerDesignation"] == "Dana"

    def test_rewrite_speaker_labels_cleans_up_new_podlove_when_later_dote_write_fails(self, audio, mocker):
        transcript = create_transcript(
            audio=audio,
            podlove={"transcripts": [{"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Hello"}]},
            dote={"lines": [{"speakerDesignation": "Speaker 2", "text": "Hi"}]},
        )
        old_podlove_name = transcript.podlove.name
        old_dote_name = transcript.dote.name
        storage = transcript.podlove.storage
        original_save = storage.save
        saved_names = []

        def fail_dote_save(name, content, *args, **kwargs):
            saved_names.append(name)
            if "dote" in name:
                raise OSError("dote write failed")
            return original_save(name, content, *args, **kwargs)

        mocker.patch.object(storage, "save", side_effect=fail_dote_save)

        with pytest.raises(OSError, match="dote write failed"):
            transcript.rewrite_speaker_labels({"Speaker 1": "Alice", "Speaker 2": "Bob"})

        persisted = Transcript.objects.get(pk=transcript.pk)
        assert transcript.podlove.name == old_podlove_name
        assert transcript.dote.name == old_dote_name
        assert persisted.podlove.name == old_podlove_name
        assert persisted.dote.name == old_dote_name
        assert storage.exists(old_podlove_name)
        assert storage.exists(old_dote_name)
        assert not storage.exists(saved_names[0])
        with persisted.podlove.open("r") as podlove_file:
            assert json.load(podlove_file)["transcripts"][0]["speaker"] == "Speaker 1"
        with persisted.dote.open("r") as dote_file:
            assert json.load(dote_file)["lines"][0]["speakerDesignation"] == "Speaker 2"

    def test_rewrite_speaker_labels_cleans_up_new_files_when_db_save_fails(self, audio, mocker):
        transcript = create_transcript(
            audio=audio,
            podlove={"transcripts": [{"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Hello"}]},
            dote={"lines": [{"speakerDesignation": "Speaker 2", "text": "Hi"}]},
        )
        old_podlove_name = transcript.podlove.name
        old_dote_name = transcript.dote.name
        storage = transcript.podlove.storage
        original_save = storage.save
        saved_names = []

        def recording_save(name, content, *args, **kwargs):
            saved_name = original_save(name, content, *args, **kwargs)
            saved_names.append(saved_name)
            return saved_name

        mocker.patch.object(storage, "save", side_effect=recording_save)
        mocker.patch.object(Transcript, "save", autospec=True, side_effect=RuntimeError("db save failed"))

        with pytest.raises(RuntimeError, match="db save failed"):
            transcript.rewrite_speaker_labels({"Speaker 1": "Alice", "Speaker 2": "Bob"})

        persisted = Transcript.objects.get(pk=transcript.pk)
        assert transcript.podlove.name == old_podlove_name
        assert transcript.dote.name == old_dote_name
        assert persisted.podlove.name == old_podlove_name
        assert persisted.dote.name == old_dote_name
        assert storage.exists(old_podlove_name)
        assert storage.exists(old_dote_name)
        assert saved_names
        assert all(not storage.exists(name) for name in saved_names)
        with persisted.podlove.open("r") as podlove_file:
            assert json.load(podlove_file)["transcripts"][0]["speaker"] == "Speaker 1"
        with persisted.dote.open("r") as dote_file:
            assert json.load(dote_file)["lines"][0]["speakerDesignation"] == "Speaker 2"

    def test_rewrite_speaker_labels_returns_false_without_changes(self, audio):
        transcript = create_transcript(
            audio=audio,
            podlove={"transcripts": [{"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Hello"}]},
            vtt="WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n<v Speaker 1>Hello\n",
        )

        assert not transcript.rewrite_speaker_labels({})
        assert not transcript.rewrite_speaker_labels({"Speaker 1": "Speaker 1"})
        assert not transcript.rewrite_speaker_labels({"Speaker 2": "Alice"})
        with transcript.vtt.open("r") as vtt_file:
            assert vtt_file.read() == "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n<v Speaker 1>Hello\n"

    def test_rewrite_speaker_labels_ignores_missing_vtt_file(self, audio):
        transcript = create_transcript(
            audio=audio,
            vtt="WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n<v Speaker 1>Hello\n",
        )
        transcript.vtt.storage.delete(transcript.vtt.name)

        assert not transcript.rewrite_speaker_labels({"Speaker 1": "Alice"})

    def test_save_json_file_handles_missing_existing_file(self, audio):
        transcript = create_transcript(audio=audio, podlove={"transcripts": []})
        transcript.podlove.storage.delete(transcript.podlove.name)

        transcript._save_json_file("podlove", {"transcripts": [{"speaker": "Speaker 1"}]})

        with transcript.podlove.open("r") as podlove_file:
            assert json.load(podlove_file)["transcripts"] == [{"speaker": "Speaker 1"}]
