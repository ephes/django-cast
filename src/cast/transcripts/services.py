"""Transcript orchestration services that operate on model instances."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import TYPE_CHECKING

from django.utils import timezone

from cast.file_replacement import StagedFileReplacementGroup
from cast.media_derivation import save_transcript_with_derivations

from . import dote, known_speakers, parsing, podlove, speaker_samples, voice_references, webvtt

if TYPE_CHECKING:
    from cast.models.transcript import Transcript


def sync_speaker_mappings(transcript: Transcript) -> None:
    """Synchronize durable anonymous-speaker mapping rows with raw artifacts."""
    ReviewState = transcript.speaker_mappings.model.ReviewState
    if transcript.pk is None:
        return
    speaker_labels = transcript.get_speaker_labels()
    seen_labels = set(speaker_labels)
    fingerprint = transcript.transcript_artifact_fingerprint()
    now = timezone.now()
    existing_mappings = {mapping.speaker_label: mapping for mapping in transcript.speaker_mappings.all()}

    for speaker_label in speaker_labels:
        mapping = existing_mappings.get(speaker_label)
        if mapping is None:
            transcript.speaker_mappings.create(
                speaker_label=speaker_label,
                source_artifact_fingerprint=fingerprint,
                last_seen=now,
            )
            continue
        update_fields = []
        if not mapping.active:
            mapping.active = True
            update_fields.append("active")
        if mapping.last_seen != now:
            mapping.last_seen = now
            update_fields.append("last_seen")
        if mapping.review_state == ReviewState.APPROVED:
            if mapping.contributor_id is None and not mapping.display_name:
                mapping.review_state = ReviewState.STALE
                update_fields.append("review_state")
            elif mapping.source_artifact_fingerprint != fingerprint:
                mapping.review_state = ReviewState.STALE
                update_fields.append("review_state")
        elif mapping.source_artifact_fingerprint != fingerprint:
            mapping.source_artifact_fingerprint = fingerprint
            update_fields.append("source_artifact_fingerprint")
        if update_fields:
            mapping.save(update_fields=update_fields)

    for speaker_label, mapping in existing_mappings.items():
        if speaker_label in seen_labels:
            continue
        update_fields = []
        if mapping.active:
            mapping.active = False
            update_fields.append("active")
        if mapping.review_state == ReviewState.APPROVED:
            mapping.review_state = ReviewState.STALE
            update_fields.append("review_state")
        if update_fields:
            mapping.save(update_fields=update_fields)


def apply_known_speaker_suggestions(transcript: Transcript, *, smooth: bool = True) -> int:
    """Apply known-speaker suggestions to public transcript output.

    Editor approval step: confident (non-uncertain) per-segment suggestions
    are written into the public Podlove ``speaker``/``voice``, DOTe
    ``speakerDesignation``, and WebVTT voice-label fields, matched to
    segments or cues by start time.

    With ``smooth=True`` (the default), uncertain segments are filled with
    the surrounding confident speaker (carry the previous confident speaker
    forward, backfill any leading gap) so the public transcript reads
    continuously instead of showing speaker-less paragraphs between labeled
    ones. With ``smooth=False`` only confident segments are labeled and
    uncertain ones are left blank for review.

    Explicit per-segment editor decisions stored in the private sidecar
    take precedence over the confident/smoothed result. Rejected segments
    clear any existing public speaker label for that start time.

    The raw Voxhelm metadata in the private ``speakers`` sidecar is
    preserved, so the raw per-segment candidates and uncertainty flags stay
    available for audit and re-application. Returns the number of public
    transcript entries matched across stored formats.
    """
    suggestions = sorted(transcript.get_speaker_suggestions(), key=parsing.segment_sort_key)
    display_names = known_speakers.resolve_display_names(suggestions, smooth=smooth)
    names_by_start_ms: dict[int, str] = {}
    rejected_start_ms: set[int] = set()
    for segment, name in zip(suggestions, display_names):
        try:
            start_ms = int(round(float(segment["start"]) * 1000))
        except (TypeError, ValueError, KeyError):
            continue
        if name:
            names_by_start_ms[start_ms] = name
            rejected_start_ms.discard(start_ms)
        elif known_speakers.segment_has_reject_decision(segment):
            rejected_start_ms.add(start_ms)
    if not names_by_start_ms and not rejected_start_ms:
        return 0
    replacements = StagedFileReplacementGroup()
    try:
        applied = transcript._clear_suggestions_from_podlove(rejected_start_ms, replacements=replacements)
        applied += transcript._clear_suggestions_from_dote(rejected_start_ms, replacements=replacements)
        if transcript.vtt:
            applied += transcript._clear_suggestions_from_webvtt(rejected_start_ms, replacements=replacements)
        if names_by_start_ms:
            applied += transcript._apply_suggestions_to_podlove(names_by_start_ms, replacements=replacements)
            applied += transcript._apply_suggestions_to_dote(names_by_start_ms, replacements=replacements)
            if transcript.vtt:
                applied += transcript._apply_suggestions_to_webvtt(names_by_start_ms, replacements=replacements)
        if applied:
            if replacements.replacements:
                replacements.save_model(transcript, save=save_transcript_with_derivations)
            else:
                save_transcript_with_derivations(transcript)
    except Exception:
        replacements.rollback()
        raise
    return applied


def save_known_speaker_editor_decisions(
    transcript: Transcript,
    decisions_by_position: Mapping[int, Mapping[str, str] | None],
) -> int:
    """Persist per-segment editor decisions in the private sidecar.

    Decisions are additive metadata on each segment. Raw Voxhelm fields
    such as ``speaker``, ``speaker_uncertain``, candidate lists, confidence,
    margin, and raw diarization labels are never overwritten.
    """
    data = transcript.speakers_data
    segments = data.get("segments")
    if not isinstance(segments, list):
        return 0
    changed = 0
    suggestion_position = -1
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        suggestion_position += 1
        if suggestion_position not in decisions_by_position:
            continue
        decision = known_speakers.normalize_editor_decision(decisions_by_position[suggestion_position])
        existing_decision = known_speakers.normalize_editor_decision(
            segment.get(known_speakers.KNOWN_SPEAKER_EDITOR_DECISION_FIELD)
        )
        if decision is None:
            if known_speakers.KNOWN_SPEAKER_EDITOR_DECISION_FIELD in segment:
                del segment[known_speakers.KNOWN_SPEAKER_EDITOR_DECISION_FIELD]
                changed += 1
            continue
        if existing_decision == decision:
            continue
        segment[known_speakers.KNOWN_SPEAKER_EDITOR_DECISION_FIELD] = decision
        changed += 1
    if not changed:
        return 0
    replacements = StagedFileReplacementGroup()
    try:
        transcript._write_speakers_data(data, replacements=replacements)
        replacements.save_model(
            transcript,
            update_fields=["speakers"],
            save=save_transcript_with_derivations,
        )
    except Exception:
        replacements.rollback()
        raise
    return changed


def rewrite_speaker_labels(transcript: Transcript, mapping: Mapping[str, str]) -> bool:
    """Rewrite speaker labels in stored transcript artifacts.

    The mapping is destructive: matching Podlove ``speaker``/``voice``,
    DOTe ``speakerDesignation``, and WebVTT voice-label values are replaced
    in-place.
    """
    cleaned_mapping: dict[str, str] = {}
    for source, target in mapping.items():
        source_label = parsing.clean_speaker_label(source)
        target_label = parsing.clean_speaker_label(target)
        if source_label and target_label and source_label != target_label:
            cleaned_mapping[source_label] = target_label
    if not cleaned_mapping:
        return False

    changed_fields = []
    replacements = StagedFileReplacementGroup()
    try:
        podlove_data = transcript._load_transcript_json("podlove")
        if podlove.rewrite_speakers(podlove_data, cleaned_mapping):
            transcript._save_json_file("podlove", podlove_data, replacements=replacements)
            changed_fields.append("podlove")

        dote_data = transcript._load_transcript_json("dote")
        if dote.rewrite_speakers(dote_data, cleaned_mapping):
            transcript._save_json_file("dote", dote_data, replacements=replacements)
            changed_fields.append("dote")

        if transcript.vtt:
            vtt_content = transcript._load_text_file("vtt")
            rewritten_vtt_content, vtt_changed = webvtt.rewrite_speakers(vtt_content, cleaned_mapping)
            if vtt_changed:
                transcript._save_text_file("vtt", rewritten_vtt_content, replacements=replacements)
                changed_fields.append("vtt")

        if not changed_fields:
            return False
        replacements.save_model(
            transcript,
            update_fields=changed_fields,
            save=save_transcript_with_derivations,
        )
    except Exception:
        replacements.rollback()
        raise
    return True


def get_speaker_labels(transcript: Transcript) -> list[str]:
    """Return unique speaker labels used by the Podlove and DOTe transcript files."""
    labels = set()
    podlove_data = transcript._load_transcript_json("podlove")
    for segment in podlove_data.get("transcripts", []):
        if not isinstance(segment, dict):
            continue
        for field_name in ("speaker", "voice"):
            label = parsing.clean_speaker_label(segment.get(field_name))
            if label:
                labels.add(label)

    dote_data = transcript._load_transcript_json("dote")
    for line in dote_data.get("lines", []):
        if not isinstance(line, dict):
            continue
        label = parsing.clean_speaker_label(line.get("speakerDesignation"))
        if label:
            labels.add(label)
    if transcript.vtt:
        labels.update(webvtt.get_speaker_labels(transcript._load_text_file("vtt")))
    return sorted(labels)


def get_speaker_samples(
    transcript: Transcript,
    *,
    limit: int = speaker_samples.SPEAKER_SAMPLE_LIMIT,
    max_chars: int = speaker_samples.SPEAKER_SAMPLE_MAX_CHARS,
    min_chars: int = speaker_samples.SPEAKER_SAMPLE_MIN_CHARS,
    min_words: int = speaker_samples.SPEAKER_SAMPLE_MIN_WORDS,
) -> dict[str, list[speaker_samples.TranscriptSpeakerSample]]:
    # Guard before touching transcript files: degenerate arguments must not
    # trigger file IO, matching the pre-extraction model behavior.
    if limit <= 0:
        return {}
    podlove_data = transcript._load_transcript_json("podlove")
    dote_data = transcript._load_transcript_json("dote")
    return speaker_samples.get_speaker_samples(
        podlove_data,
        dote_data,
        limit=limit,
        max_chars=max_chars,
        min_chars=min_chars,
        min_words=min_words,
    )


def get_voice_reference_candidates(
    transcript: Transcript,
    *,
    target_seconds: Decimal = voice_references.VOICE_REFERENCE_CANDIDATE_TARGET_SECONDS,
    min_seconds: Decimal = voice_references.VOICE_REFERENCE_CANDIDATE_MIN_SECONDS,
    max_gap_seconds: Decimal = voice_references.VOICE_REFERENCE_CANDIDATE_MAX_GAP_SECONDS,
    limit_per_speaker: int = voice_references.VOICE_REFERENCE_CANDIDATE_LIMIT,
) -> list[voice_references.TranscriptVoiceReferenceCandidate]:
    # Guard before touching transcript files: degenerate arguments must not
    # trigger file IO, matching the pre-extraction model behavior.
    if limit_per_speaker <= 0:
        return []
    target_seconds = parsing.quantize_seconds(Decimal(str(target_seconds)))
    min_seconds = parsing.quantize_seconds(Decimal(str(min_seconds)))
    max_gap_seconds = parsing.quantize_seconds(Decimal(str(max_gap_seconds)))
    if target_seconds <= 0 or min_seconds <= 0 or max_gap_seconds < 0:
        return []
    podlove_data = transcript._load_transcript_json("podlove")
    return voice_references.get_candidates(
        podlove_data,
        target_seconds=target_seconds,
        min_seconds=min_seconds,
        max_gap_seconds=max_gap_seconds,
        limit_per_speaker=limit_per_speaker,
    )
