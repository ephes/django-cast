"""Pure Podlove transcript transforms."""

import copy
from collections.abc import Mapping
from typing import Any

from . import parsing


def parse_start_ms(value: object) -> int | None:
    """Admit a Podlove edit identity without boolean or numeric coercion."""
    return value if type(value) is int and value >= 0 else None


def validate_edit_times(data: dict) -> None:
    """Refuse boolean aliases before an editorial operation stages any files."""
    segments = data.get("transcripts")
    if not isinstance(segments, list):
        return
    for segment in segments:
        if isinstance(segment, dict) and isinstance(segment.get("start_ms"), bool):
            raise parsing.TranscriptArtifactError(
                "Invalid Podlove millisecond identity: boolean start_ms. Replace the artifact and reload."
            )


def apply_suggestions(data: dict, names_by_start_ms: Mapping[int, str]) -> int:
    segments = data.get("transcripts")
    if not isinstance(segments, list):
        return 0
    applied = 0
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        start_ms = parse_start_ms(segment.get("start_ms"))
        if start_ms is None:
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
        start_ms = parse_start_ms(segment.get("start_ms"))
        if start_ms is None or start_ms not in start_milliseconds:
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
        start_ms, text = parse_start_ms(segment.get("start_ms")), segment.get("text")
        if start_ms is not None and isinstance(text, str):
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
        start_ms = parse_start_ms(segment.get("start_ms"))
        text = texts_by_start_ms.get(start_ms) if start_ms is not None else None
        if text is not None and segment.get("text") != text:
            segment["text"] = text
            changed += 1
    return changed


PODLOVE_SPEAKER_FIELDS = ("speaker", "voice")


def apply_speaker_mapping_to_podlove_data(data: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    if not mapping:
        return data
    mapped = copy.deepcopy(data)
    if isinstance(mapped.get("transcripts", []), list):
        rewrite_speakers(mapped, mapping)
    return mapped


def sanitize_podlove_data(data: dict[str, Any], allowed_speaker_labels: set[str] | None) -> dict[str, Any]:
    if allowed_speaker_labels is None:
        return data

    transcripts = data.get("transcripts", [])
    if not isinstance(transcripts, list):
        return data

    needs_sanitization = False
    for segment in transcripts:
        if not isinstance(segment, dict):
            continue
        for field_name in PODLOVE_SPEAKER_FIELDS:
            label = parsing.clean_speaker_label(segment.get(field_name))
            if field_name in segment and (
                not isinstance(segment[field_name], str) or (label and label not in allowed_speaker_labels)
            ):
                needs_sanitization = True
                break
        if needs_sanitization:
            break
    if not needs_sanitization:
        return data

    sanitized = copy.deepcopy(data)
    sanitized_transcripts = sanitized.get("transcripts", [])
    for segment in sanitized_transcripts:
        if not isinstance(segment, dict):
            continue
        for field_name in PODLOVE_SPEAKER_FIELDS:
            label = parsing.clean_speaker_label(segment.get(field_name))
            if field_name in segment and (
                not isinstance(segment[field_name], str) or (label and label not in allowed_speaker_labels)
            ):
                segment.pop(field_name, None)
    return sanitized


def podlove_contributors_from_data(data: dict[str, Any]) -> list[dict[str, str]]:
    contributors: list[dict[str, str]] = []
    seen: set[str] = set()
    transcripts = data.get("transcripts", [])
    if not isinstance(transcripts, list):
        return contributors
    for segment in transcripts:
        if not isinstance(segment, dict):
            continue
        for field_name in PODLOVE_SPEAKER_FIELDS:
            label = segment.get(field_name)
            if isinstance(label, str) and label.strip() and label not in seen:
                seen.add(label)
                contributors.append({"id": label, "name": label})
    return contributors
