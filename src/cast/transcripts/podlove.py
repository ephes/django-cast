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
