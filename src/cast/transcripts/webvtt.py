"""Pure WebVTT transcript transforms."""

import re
from collections.abc import Mapping

from . import parsing

TIMING_SEPARATOR = "-->"
VOICE_OPENING_RE = re.compile(r"<v(?P<classes>(?:\.[^\s>]+)*)(?:\s+(?P<label>[^>]*))?>")
VOICE_CLOSING_RE = re.compile(r"</v>")
GENERIC_SPEAKER_PREFIX_RE = re.compile(r"^(?P<label>Speaker\s+\d+)\s*:\s*(?P<text>.*)$", re.IGNORECASE)


def webvtt_timestamp_to_ms(value: object) -> int | None:
    """Parse a WebVTT ``HH:MM:SS.mmm`` or ``MM:SS.mmm`` timestamp into milliseconds."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"(?:(\d+):)?(\d{2}):(\d{2})\.(\d{1,3})", value.strip())
    if match is None:
        return None
    hours, minutes, seconds, millis = match.groups()
    return ((int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds)) * 1000) + int(millis.ljust(3, "0"))


def timing_line_start_ms(line: str) -> int | None:
    start_timestamp = line.split(TIMING_SEPARATOR, 1)[0].strip()
    return webvtt_timestamp_to_ms(start_timestamp)


def get_speaker_labels(content: str) -> set[str]:
    labels: set[str] = set()
    in_cue_payload = False
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            in_cue_payload = False
            continue
        if TIMING_SEPARATOR in line:
            in_cue_payload = True
            continue
        if not in_cue_payload:
            continue
        for match in VOICE_OPENING_RE.finditer(line):
            label = parsing.clean_speaker_label(match.group("label"))
            if label:
                labels.add(label)
        generic_prefix_match = GENERIC_SPEAKER_PREFIX_RE.match(stripped)
        if generic_prefix_match is not None:
            label = parsing.clean_speaker_label(generic_prefix_match.group("label"))
            labels.add(label)
    return labels


def clear_suggestions_from_content(content: str, start_milliseconds: set[int]) -> tuple[str, int, bool]:
    rewritten_lines: list[str] = []
    payload_lines: list[str] | None = None
    should_clear = False
    applied = 0
    changed = False

    def flush_payload() -> None:
        nonlocal applied, changed, payload_lines, should_clear
        if payload_lines is None:
            return
        lines = payload_lines
        if should_clear:
            lines, cue_changed, cue_applied = clear_cue_voice(lines)
            if cue_applied:
                applied += 1
            changed = changed or cue_changed
        rewritten_lines.extend(lines)
        payload_lines = None
        should_clear = False

    for line in content.splitlines(keepends=True):
        if payload_lines is not None:
            if not line.strip():
                flush_payload()
                rewritten_lines.append(line)
            else:
                payload_lines.append(line)
            continue

        if TIMING_SEPARATOR in line:
            start_ms = timing_line_start_ms(line)
            should_clear = start_ms in start_milliseconds if start_ms is not None else False
            payload_lines = []
        rewritten_lines.append(line)

    flush_payload()
    return "".join(rewritten_lines), applied, changed


def clear_cue_voice(lines: list[str]) -> tuple[list[str], bool, bool]:
    if not lines:
        return lines, False, False
    rewritten_lines = []
    changed = False
    for line in lines:
        rewritten_line = VOICE_OPENING_RE.sub("", line)
        rewritten_line = VOICE_CLOSING_RE.sub("", rewritten_line)
        changed = changed or rewritten_line != line
        rewritten_lines.append(rewritten_line)
    return rewritten_lines, changed, True


def apply_suggestions_to_content(content: str, names_by_start_ms: Mapping[int, str]) -> tuple[str, int, bool]:
    rewritten_lines: list[str] = []
    payload_lines: list[str] | None = None
    current_name: str | None = None
    applied = 0
    changed = False

    def flush_payload() -> None:
        nonlocal applied, changed, current_name, payload_lines
        if payload_lines is None:
            return
        lines = payload_lines
        if current_name:
            lines, cue_changed, cue_applied = set_cue_voice(lines, current_name)
            if cue_applied:
                applied += 1
            changed = changed or cue_changed
        rewritten_lines.extend(lines)
        current_name = None
        payload_lines = None

    for line in content.splitlines(keepends=True):
        if payload_lines is not None:
            if not line.strip():
                flush_payload()
                rewritten_lines.append(line)
            else:
                payload_lines.append(line)
            continue

        if TIMING_SEPARATOR in line:
            start_ms = timing_line_start_ms(line)
            current_name = names_by_start_ms.get(start_ms) if start_ms is not None else None
            payload_lines = []
        rewritten_lines.append(line)

    flush_payload()
    return "".join(rewritten_lines), applied, changed


def set_cue_voice(lines: list[str], name: str) -> tuple[list[str], bool, bool]:
    rewritten_lines = []
    changed = False
    has_voice_opening = False
    for line in lines:
        rewritten_line, line_changed, line_has_voice_opening = set_payload_line_voice(line, name)
        rewritten_lines.append(rewritten_line)
        changed = changed or line_changed
        has_voice_opening = has_voice_opening or line_has_voice_opening
    if has_voice_opening:
        return rewritten_lines, changed, True
    if not rewritten_lines:
        return rewritten_lines, False, False
    rewritten_lines[0] = f"{voice_opening(name)}{rewritten_lines[0]}"
    return rewritten_lines, True, True


def set_payload_line_voice(line: str, name: str) -> tuple[str, bool, bool]:
    rewritten_line, replacements = VOICE_OPENING_RE.subn(
        lambda _match: voice_opening(name),
        line,
    )
    return rewritten_line, rewritten_line != line, replacements > 0


def rewrite_speakers(content: str, mapping: Mapping[str, str]) -> tuple[str, bool]:
    rewritten_lines = []
    changed = False
    in_cue_payload = False
    for line in content.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped:
            in_cue_payload = False
            rewritten_lines.append(line)
        elif TIMING_SEPARATOR in line:
            in_cue_payload = True
            rewritten_lines.append(line)
        elif in_cue_payload:
            line, line_changed = rewrite_payload_line(line, mapping)
            changed = changed or line_changed
            rewritten_lines.append(line)
        else:
            rewritten_lines.append(line)
    return "".join(rewritten_lines), changed


def rewrite_payload_line(line: str, mapping: Mapping[str, str]) -> tuple[str, bool]:
    def replace_voice_opening(match: re.Match[str]) -> str:
        label = parsing.clean_speaker_label(match.group("label"))
        target_label = mapping.get(label)
        if target_label is None:
            return match.group(0)
        return voice_opening(target_label, classes=match.group("classes"))

    rewritten_line = VOICE_OPENING_RE.sub(replace_voice_opening, line)
    return rewritten_line, rewritten_line != line


def voice_opening(label: str, *, classes: str = "") -> str:
    return f"<v{classes} {label}>"
