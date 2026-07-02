"""Pure DOTe transcript transforms."""

import re
from collections.abc import Mapping
from typing import Any

from . import parsing


def dote_timestamp_to_ms(value: object) -> int | None:
    """Parse a DOTe ``HH:MM:SS,mmm`` timestamp into milliseconds."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})", value.strip())
    if match is None:
        return None
    hours, minutes, seconds, millis = (int(part) for part in match.groups())
    return ((hours * 3600 + minutes * 60 + seconds) * 1000) + millis


def apply_suggestions(data: dict, names_by_start_ms: Mapping[int, str]) -> int:
    lines = data.get("lines")
    if not isinstance(lines, list):
        return 0
    applied = 0
    for line in lines:
        if not isinstance(line, dict):
            continue
        start_ms = dote_timestamp_to_ms(line.get("startTime"))
        if start_ms is None:
            continue
        name = names_by_start_ms.get(start_ms)
        if name:
            line["speakerDesignation"] = name
            applied += 1
    return applied


def clear_suggestions(data: dict, start_milliseconds: set[int]) -> tuple[int, bool]:
    lines = data.get("lines")
    if not isinstance(lines, list):
        return 0, False
    applied = 0
    changed = False
    for line in lines:
        if not isinstance(line, dict):
            continue
        start_ms = dote_timestamp_to_ms(line.get("startTime"))
        if start_ms is None or start_ms not in start_milliseconds:
            continue
        applied += 1
        changed = changed or line.get("speakerDesignation") != ""
        line["speakerDesignation"] = ""
    return applied, changed


def rewrite_speakers(data: dict[str, Any], mapping: Mapping[str, str]) -> bool:
    changed = False
    for line in data.get("lines", []):
        if not isinstance(line, dict):
            continue
        label = parsing.clean_speaker_label(line.get("speakerDesignation"))
        if label in mapping:
            line["speakerDesignation"] = mapping[label]
            changed = True
    return changed


def time_to_seconds(time_str) -> float:
    match = re.match(r"(\d+):(\d+):(\d+),(\d+)", time_str)
    if match:
        hours, minutes, seconds, milliseconds = map(int, match.groups())
        return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
    raise ValueError(f"Invalid time format: {time_str}")


def convert_segments(segments) -> list[dict]:
    converted = []
    for segment in segments:
        converted.append(
            {
                "startTime": time_to_seconds(segment["startTime"]),
                "endTime": time_to_seconds(segment["endTime"]),
                "speaker": segment["speakerDesignation"],
                "body": segment["text"],
            }
        )
    return converted


def convert_dote_to_podcastindex_transcript(transcript: dict) -> dict:
    return {
        "version": "1.0",
        "segments": convert_segments(transcript["lines"]),
    }
