"""Pure known-speaker suggestion helpers."""

from collections.abc import Mapping

from . import parsing

KNOWN_SPEAKER_EDITOR_DECISION_FIELD = "editor_decision"
KNOWN_SPEAKER_DECISION_APPROVE = "approve"
KNOWN_SPEAKER_DECISION_CORRECT = "correct"
KNOWN_SPEAKER_DECISION_REJECT = "reject"


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


def resolve_display_names(suggestions: list[dict], *, smooth: bool) -> list[str | None]:
    """Per-segment display speaker: confident as-is, uncertain smoothed.

    Smoothing carries the previous confident speaker forward over uncertain
    segments, then backfills any leading uncertain run from the first
    confident speaker, so every segment between known speakers is attributed.
    """
    confident: list[str | None] = []
    for segment in suggestions:
        name = segment.get("speaker")
        confident.append(name if (name and not segment.get("speaker_uncertain")) else None)
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
