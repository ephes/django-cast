"""Pure voice-reference candidate extraction helpers."""

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

from . import parsing

VOICE_REFERENCE_CANDIDATE_LIMIT = 3
VOICE_REFERENCE_CANDIDATE_TARGET_SECONDS = Decimal("30.000")
VOICE_REFERENCE_CANDIDATE_MIN_SECONDS = Decimal("8.000")
VOICE_REFERENCE_CANDIDATE_MAX_GAP_SECONDS = Decimal("2.000")
VOICE_REFERENCE_CANDIDATE_MAX_CHARS = 240


@dataclass(frozen=True)
class TranscriptVoiceReferenceCandidate:
    """Timed clean-solo source-range candidate derived from diarized transcript data."""

    speaker_label: str
    start_seconds: Decimal
    end_seconds: Decimal
    duration_seconds: Decimal
    text: str
    rank: int

    @property
    def start_timestamp_label(self) -> str:
        return parsing.format_decimal_timestamp(self.start_seconds)

    @property
    def end_timestamp_label(self) -> str:
        return parsing.format_decimal_timestamp(self.end_seconds)

    @property
    def duration_label(self) -> str:
        return parsing.format_decimal_timestamp(self.duration_seconds)


@dataclass(frozen=True)
class _PodloveVoiceReferenceSegment:
    speaker_label: str
    start_seconds: Decimal
    end_seconds: Decimal
    text: str
    position: int


def get_candidates(
    podlove_data: dict,
    *,
    target_seconds: Decimal = VOICE_REFERENCE_CANDIDATE_TARGET_SECONDS,
    min_seconds: Decimal = VOICE_REFERENCE_CANDIDATE_MIN_SECONDS,
    max_gap_seconds: Decimal = VOICE_REFERENCE_CANDIDATE_MAX_GAP_SECONDS,
    limit_per_speaker: int = VOICE_REFERENCE_CANDIDATE_LIMIT,
) -> list[TranscriptVoiceReferenceCandidate]:
    """Return source-range candidates derived from diarized Podlove segments.

    Candidates are contiguous, same-label Podlove runs with usable start and
    end times. Derivation is read-only: transcript files and private
    known-speaker sidecars are never mutated by this helper.
    """
    if limit_per_speaker <= 0:
        return []
    target_seconds = parsing.quantize_seconds(Decimal(str(target_seconds)))
    min_seconds = parsing.quantize_seconds(Decimal(str(min_seconds)))
    max_gap_seconds = parsing.quantize_seconds(Decimal(str(max_gap_seconds)))
    if target_seconds <= 0 or min_seconds <= 0 or max_gap_seconds < 0:
        return []

    candidates_by_speaker: dict[str, list[TranscriptVoiceReferenceCandidate]] = {}
    for run in get_runs(podlove_data, max_gap_seconds=max_gap_seconds):
        candidate = build_candidate_from_run(
            run,
            target_seconds=target_seconds,
            min_seconds=min_seconds,
        )
        if candidate is None:
            continue
        candidates_by_speaker.setdefault(candidate.speaker_label, []).append(candidate)

    ranked_candidates: list[TranscriptVoiceReferenceCandidate] = []
    for speaker_label in sorted(candidates_by_speaker):
        speaker_candidates = sorted(
            candidates_by_speaker[speaker_label],
            key=lambda candidate: (-candidate.duration_seconds, candidate.start_seconds, candidate.end_seconds),
        )
        for rank, candidate in enumerate(speaker_candidates[:limit_per_speaker], start=1):
            ranked_candidates.append(replace(candidate, rank=rank))
    return ranked_candidates


def get_runs(
    podlove_data: dict, *, max_gap_seconds: Decimal = VOICE_REFERENCE_CANDIDATE_MAX_GAP_SECONDS
) -> list[list[_PodloveVoiceReferenceSegment]]:
    runs: list[list[_PodloveVoiceReferenceSegment]] = []
    current_run: list[_PodloveVoiceReferenceSegment] = []
    for position, segment in enumerate(podlove_data.get("transcripts", [])):
        parsed_segment = parse_segment(segment, position=position)
        if parsed_segment is None:
            if current_run:
                runs.append(current_run)
                current_run = []
            continue
        if (
            current_run
            and parsed_segment.speaker_label == current_run[-1].speaker_label
            and Decimal("0") <= parsed_segment.start_seconds - current_run[-1].end_seconds <= max_gap_seconds
        ):
            current_run.append(parsed_segment)
        else:
            if current_run:
                runs.append(current_run)
            current_run = [parsed_segment]
    if current_run:
        runs.append(current_run)
    return runs


def parse_segment(segment: Any, *, position: int) -> _PodloveVoiceReferenceSegment | None:
    if not isinstance(segment, dict):
        return None
    speaker_labels = {
        label for field_name in ("speaker", "voice") if (label := parsing.clean_speaker_label(segment.get(field_name)))
    }
    if len(speaker_labels) != 1:
        return None
    text = parsing.clean_sample_text(segment.get("text"))
    if not text:
        return None
    start_seconds = parsing.parse_record_decimal_seconds(
        segment,
        millisecond_field="start_ms",
        timestamp_fields=("start", "startTime"),
    )
    end_seconds = parsing.parse_record_decimal_seconds(
        segment,
        millisecond_field="end_ms",
        timestamp_fields=("end", "endTime"),
    )
    if start_seconds is None or end_seconds is None or start_seconds >= end_seconds:
        return None
    return _PodloveVoiceReferenceSegment(
        speaker_label=next(iter(speaker_labels)),
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        text=text,
        position=position,
    )


def build_candidate_from_run(
    run: list[_PodloveVoiceReferenceSegment],
    *,
    target_seconds: Decimal,
    min_seconds: Decimal,
) -> TranscriptVoiceReferenceCandidate | None:
    if not run:
        return None
    start_seconds = run[0].start_seconds
    uncapped_end_seconds = run[-1].end_seconds
    end_seconds = min(uncapped_end_seconds, start_seconds + target_seconds)
    duration_seconds = parsing.quantize_seconds(end_seconds - start_seconds)
    if duration_seconds < min_seconds:
        return None
    text = parsing.truncate_sample_text(
        " ".join(segment.text for segment in run if segment.start_seconds < end_seconds),
        max_chars=VOICE_REFERENCE_CANDIDATE_MAX_CHARS,
    )
    return TranscriptVoiceReferenceCandidate(
        speaker_label=run[0].speaker_label,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        duration_seconds=duration_seconds,
        text=text,
        rank=0,
    )
