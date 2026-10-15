"""Pure Podlove transcript transforms."""

from collections.abc import Mapping
from typing import Any

from . import parsing


def apply_suggestions(data: dict, names_by_start_ms: Mapping[int, str]) -> int:
    segments = data.get("transcripts")
    if not isinstance(segments, list):
        return 0
    applied = 0
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        start_ms = segment.get("start_ms")
        if not isinstance(start_ms, int):
            continue
        name = names_by_start_ms.get(start_ms)
        if name:
            segment["speaker"] = name
            segment["voice"] = name
            applied += 1
    return applied


def clear_suggestions(data: dict, start_milliseconds: set[int]) -> tuple[int, bool]:
    segments = data.get("transcripts")
    if not isinstance(segments, list):
        return 0, False
    applied = 0
    changed = False
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        start_ms = segment.get("start_ms")
        if not isinstance(start_ms, int) or start_ms not in start_milliseconds:
            continue
        applied += 1
        changed = changed or segment.get("speaker") != "" or segment.get("voice") != ""
        segment["speaker"] = ""
        segment["voice"] = ""
    return applied, changed


def rewrite_speakers(data: dict[str, Any], mapping: Mapping[str, str]) -> bool:
    changed = False
    for segment in data.get("transcripts", []):
        if not isinstance(segment, dict):
            continue
        for field_name in ("speaker", "voice"):
            label = parsing.clean_speaker_label(segment.get(field_name))
            if label in mapping:
                segment[field_name] = mapping[label]
                changed = True
    return changed


def get_texts(data: dict) -> list[tuple[int, str]]:
    """``(start_ms, text)`` of each segment, in order; start times used twice are left out."""
    segments = data.get("transcripts")
    if not isinstance(segments, list):
        return []
    texts: list[tuple[int, str]] = []
    counts: dict[int, int] = {}
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        start_ms, text = segment.get("start_ms"), segment.get("text")
        if isinstance(start_ms, int) and isinstance(text, str):
            texts.append((start_ms, text))
            counts[start_ms] = counts.get(start_ms, 0) + 1
    return [(start_ms, text) for start_ms, text in texts if counts[start_ms] == 1]


def set_texts(data: dict, texts_by_start_ms: Mapping[int, str]) -> int:
    """Set the ``text`` of segments matched by ``start_ms``; return how many changed."""
    segments = data.get("transcripts")
    if not isinstance(segments, list):
        return 0
    changed = 0
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        start_ms = segment.get("start_ms")
        text = texts_by_start_ms.get(start_ms) if isinstance(start_ms, int) else None
        if text is not None and segment.get("text") != text:
            segment["text"] = text
            changed += 1
    return changed
