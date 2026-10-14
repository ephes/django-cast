"""Pure known-speaker suggestion helpers."""

from collections.abc import Mapping

from . import parsing

KNOWN_SPEAKER_EDITOR_DECISION_FIELD = "editor_decision"
KNOWN_SPEAKER_DECISION_APPROVE = "approve"
KNOWN_SPEAKER_DECISION_CORRECT = "correct"
KNOWN_SPEAKER_DECISION_REJECT = "reject"
RAW_DIARIZATION_LABELS_FIELD = "raw_diarization_labels"
MIXED_SPEAKERS_REASON = "mixed_speakers"
# Fallback label vote for sidecars without ``raw_diarization_labels``; mirrors
# Voxhelm's turn-corroboration thresholds.
LABEL_VOTE_MIN_VOTES = 5
LABEL_VOTE_MIN_SHARE = 0.9


def normalize_editor_decision(decision: object) -> dict[str, str] | None:
    if not isinstance(decision, Mapping):
        return None
    action = decision.get("action")
    if action == KNOWN_SPEAKER_DECISION_REJECT:
        return {"action": KNOWN_SPEAKER_DECISION_REJECT, "speaker": ""}
    if action not in {KNOWN_SPEAKER_DECISION_APPROVE, KNOWN_SPEAKER_DECISION_CORRECT}:
        return None
    speaker = parsing.clean_speaker_label(decision.get("speaker"))
    if not speaker:
        return None
    return {"action": str(action), "speaker": speaker}


def segment_has_reject_decision(segment: Mapping[str, object]) -> bool:
    decision = normalize_editor_decision(segment.get(KNOWN_SPEAKER_EDITOR_DECISION_FIELD))
    return bool(decision and decision["action"] == KNOWN_SPEAKER_DECISION_REJECT)


def raw_label_speakers(summary: Mapping[str, object], suggestions: list[dict]) -> dict[str, str | None]:
    """Map each raw diarization label to the known speaker it belongs to, or ``None``.

    Uses the ``raw_diarization_labels`` summary that Voxhelm 0.1.7 and later
    write. Older sidecars lack it; for those the map is rebuilt from the
    segments with the same vote Voxhelm uses: confident segments accepted on
    their own voiceprint (no accept reason) vote for their speaker, and a label
    belongs to a speaker when at least ``LABEL_VOTE_MIN_VOTES`` segments vote
    and ``LABEL_VOTE_MIN_SHARE`` of them agree.
    """
    labels = summary.get(RAW_DIARIZATION_LABELS_FIELD)
    if isinstance(labels, Mapping):
        mapped: dict[str, str | None] = {}
        for label, entry in labels.items():
            if not isinstance(label, str) or not isinstance(entry, Mapping):
                continue
            speaker = entry.get("speaker")
            mapped[label] = speaker if isinstance(speaker, str) and speaker else None
        return mapped

    votes: dict[str, dict[str, int]] = {}
    for segment in suggestions:
        label = segment.get("raw_diarization_speaker")
        if not isinstance(label, str) or not label:
            continue
        speaker_votes = votes.setdefault(label, {})
        speaker = segment.get("speaker")
        if speaker and not segment.get("speaker_uncertain") and not segment.get("speaker_accept_reason"):
            speaker_votes[speaker] = speaker_votes.get(speaker, 0) + 1
    fallback: dict[str, str | None] = {}
    for label, speaker_votes in votes.items():
        fallback[label] = None
        total = sum(speaker_votes.values())
        if not total:
            continue
        speaker, count = min(speaker_votes.items(), key=lambda item: (-item[1], item[0]))
        if total >= LABEL_VOTE_MIN_VOTES and count >= LABEL_VOTE_MIN_SHARE * total:
            fallback[label] = speaker
    return fallback


def find_unmatched_label(label_speakers: Mapping[str, str | None]) -> str | None:
    """The only diarization label not tied to a known speaker, else ``None``."""
    unmatched = [label for label, speaker in label_speakers.items() if speaker is None]
    return unmatched[0] if len(unmatched) == 1 else None


def resolve_display_names(
    suggestions: list[dict],
    *,
    smooth: bool,
    label_names: Mapping[str, str] | None = None,
) -> list[str | None]:
    """Per-segment display speaker: confident as-is, uncertain smoothed.

    ``label_names`` names uncertain segments by their raw diarization label,
    for example a guest without a voice reference. Segments flagged as mixed
    speakers stay unnamed.

    Smoothing carries the previous confident speaker forward over uncertain
    segments, then backfills any leading uncertain run from the first
    confident speaker, so every segment between known speakers is attributed.
    """
    confident: list[str | None] = []
    for segment in suggestions:
        name = segment.get("speaker")
        if name and not segment.get("speaker_uncertain"):
            confident.append(name)
        else:
            label = segment.get("raw_diarization_speaker")
            mixed = segment.get("speaker_uncertain_reason") == MIXED_SPEAKERS_REASON
            confident.append(label_names.get(label) if label_names and isinstance(label, str) and not mixed else None)
    display_names: list[str | None]
    if not smooth:
        display_names = confident
    else:
        smoothed: list[str | None] = list(confident)
        last: str | None = None
        for position, name in enumerate(smoothed):
            if name is not None:
                last = name
            elif last is not None:
                smoothed[position] = last
        following: str | None = None
        for position in range(len(smoothed) - 1, -1, -1):
            if smoothed[position] is not None:
                following = smoothed[position]
            elif following is not None:
                smoothed[position] = following
        display_names = smoothed
    for position, segment in enumerate(suggestions):
        decision = normalize_editor_decision(segment.get(KNOWN_SPEAKER_EDITOR_DECISION_FIELD))
        if decision is None:
            continue
        display_names[position] = None if decision["action"] == KNOWN_SPEAKER_DECISION_REJECT else decision["speaker"]
    return display_names
