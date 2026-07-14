"""Pure speaker-sample extraction helpers."""

from dataclasses import dataclass

from . import parsing

SPEAKER_SAMPLE_LIMIT = 3
SPEAKER_SAMPLE_MAX_CHARS = 180
SPEAKER_SAMPLE_MIN_CHARS = 35
SPEAKER_SAMPLE_MIN_WORDS = 4


@dataclass(frozen=True)
class TranscriptSpeakerSample:
    """Short transcript excerpt used to identify diarized speakers in the admin."""

    text: str
    timestamp_label: str
    start_seconds: float | None

    @property
    def has_start_time(self) -> bool:
        return self.start_seconds is not None


@dataclass(frozen=True)
class _SpeakerSampleCandidate:
    speaker_label: str
    text: str
    timestamp_label: str
    start_seconds: float | None
    position: int
    useful: bool


def get_speaker_samples(
    podlove_data: dict,
    dote_data: dict,
    *,
    limit: int = SPEAKER_SAMPLE_LIMIT,
    max_chars: int = SPEAKER_SAMPLE_MAX_CHARS,
    min_chars: int = SPEAKER_SAMPLE_MIN_CHARS,
    min_words: int = SPEAKER_SAMPLE_MIN_WORDS,
) -> dict[str, list[TranscriptSpeakerSample]]:
    """Return short transcript excerpts keyed by diarization speaker label.

    Samples prefer Podlove transcript segments, use DOTe lines as a fallback,
    skip low-information backchannels where possible, and spread the chosen
    examples across each speaker's appearances.
    """
    if limit <= 0:
        return {}
    podlove_candidates = get_podlove_candidates(
        podlove_data,
        max_chars=max_chars,
        min_chars=min_chars,
        min_words=min_words,
    )
    dote_candidates = get_dote_candidates(
        dote_data,
        max_chars=max_chars,
        min_chars=min_chars,
        min_words=min_words,
    )
    return select_samples(
        podlove_candidates=podlove_candidates,
        dote_candidates=dote_candidates,
        limit=limit,
    )


def get_podlove_candidates(
    podlove_data: dict,
    *,
    max_chars: int,
    min_chars: int,
    min_words: int,
) -> list[_SpeakerSampleCandidate]:
    candidates: list[_SpeakerSampleCandidate] = []
    for position, segment in enumerate(podlove_data.get("transcripts", [])):
        if not isinstance(segment, dict):
            continue
        speaker_labels = {
            label
            for field_name in ("speaker", "voice")
            if (label := parsing.clean_speaker_label(segment.get(field_name)))
        }
        if not speaker_labels:
            continue
        text = parsing.clean_sample_text(segment.get("text"))
        if not text:
            continue
        start_seconds = parsing.parse_record_start_seconds(segment, timestamp_fields=("start", "startTime"))
        candidates.extend(
            build_candidate(
                speaker_label=speaker_label,
                text=text,
                position=position,
                start_seconds=start_seconds,
                max_chars=max_chars,
                min_chars=min_chars,
                min_words=min_words,
            )
            for speaker_label in sorted(speaker_labels)
        )
    return candidates


def get_dote_candidates(
    dote_data: dict,
    *,
    max_chars: int,
    min_chars: int,
    min_words: int,
) -> list[_SpeakerSampleCandidate]:
    candidates: list[_SpeakerSampleCandidate] = []
    for position, line in enumerate(dote_data.get("lines", [])):
        if not isinstance(line, dict):
            continue
        speaker_label = parsing.clean_speaker_label(line.get("speakerDesignation"))
        if not speaker_label:
            continue
        text = parsing.clean_sample_text(line.get("text"))
        if not text:
            continue
        start_seconds = parsing.parse_record_start_seconds(line, timestamp_fields=("startTime",))
        candidates.append(
            build_candidate(
                speaker_label=speaker_label,
                text=text,
                position=position,
                start_seconds=start_seconds,
                max_chars=max_chars,
                min_chars=min_chars,
                min_words=min_words,
            )
        )
    return candidates


def select_samples(
    *,
    podlove_candidates: list[_SpeakerSampleCandidate],
    dote_candidates: list[_SpeakerSampleCandidate],
    limit: int,
) -> dict[str, list[TranscriptSpeakerSample]]:
    samples = {}
    speaker_labels = sorted(
        {candidate.speaker_label for candidate in podlove_candidates}
        | {candidate.speaker_label for candidate in dote_candidates}
    )
    for speaker_label in speaker_labels:
        podlove_speaker_candidates = sort_candidates(
            [candidate for candidate in podlove_candidates if candidate.speaker_label == speaker_label]
        )
        dote_speaker_candidates = sort_candidates(
            [candidate for candidate in dote_candidates if candidate.speaker_label == speaker_label]
        )
        candidate_pool = (
            [candidate for candidate in podlove_speaker_candidates if candidate.useful]
            or [candidate for candidate in dote_speaker_candidates if candidate.useful]
            or podlove_speaker_candidates
            or dote_speaker_candidates
        )
        samples[speaker_label] = [
            TranscriptSpeakerSample(
                text=candidate.text,
                timestamp_label=candidate.timestamp_label,
                start_seconds=candidate.start_seconds,
            )
            for candidate in spread_candidates(candidate_pool, limit=limit)
        ]
    return samples


def sort_candidates(candidates: list[_SpeakerSampleCandidate]) -> list[_SpeakerSampleCandidate]:
    return sorted(
        candidates,
        key=lambda candidate: (
            candidate.start_seconds is None,
            candidate.start_seconds if candidate.start_seconds is not None else candidate.position,
            candidate.position,
        ),
    )


def spread_candidates(
    candidates: list[_SpeakerSampleCandidate],
    *,
    limit: int,
) -> list[_SpeakerSampleCandidate]:
    if len(candidates) <= limit:
        return candidates
    if limit == 1:
        return candidates[:1]
    last_index = len(candidates) - 1
    selected_indexes = []
    for sample_index in range(limit):
        candidate_index = int((sample_index * last_index / (limit - 1)) + 0.5)
        selected_indexes.append(candidate_index)
    return [candidates[index] for index in selected_indexes]


def build_candidate(
    *,
    speaker_label: str,
    text: str,
    position: int,
    start_seconds: float | None,
    max_chars: int,
    min_chars: int,
    min_words: int,
) -> _SpeakerSampleCandidate:
    return _SpeakerSampleCandidate(
        speaker_label=speaker_label,
        text=parsing.truncate_sample_text(text, max_chars=max_chars),
        timestamp_label=parsing.format_sample_timestamp(start_seconds),
        start_seconds=start_seconds,
        position=position,
        useful=parsing.sample_text_is_useful(text, min_chars=min_chars, min_words=min_words),
    )
