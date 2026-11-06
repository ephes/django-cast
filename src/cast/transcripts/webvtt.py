"""Pure WebVTT transcript transforms."""

import re
from collections.abc import Mapping

from . import parsing

TIMING_SEPARATOR = "-->"
VOICE_OPENING_RE = re.compile(r"<v(?P<classes>(?:\.[^\s>]+)*)(?:\s+(?P<label>[^>]*))?>")
VOICE_CLOSING_RE = re.compile(r"</v>")
VOICE_TAG_RE = re.compile(rf"(?P<opening>{VOICE_OPENING_RE.pattern})|(?P<closing>{VOICE_CLOSING_RE.pattern})")
GENERIC_SPEAKER_PREFIX_RE = re.compile(r"^(?P<label>Speaker\s+\d+)\s*:\s*(?P<text>.*)$", re.IGNORECASE)
LABEL_ECHO_SEPARATOR_RE = re.compile(r"\s*:\s*")


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


def split_line_ending(line: str) -> tuple[str, str]:
    """Split ``line`` into its body and its CRLF or LF ending (empty when there is none)."""
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    return line, ""


def match_generic_speaker_prefix(body: str) -> tuple[str, re.Match[str]] | None:
    """Match a ``Speaker N:`` prefix after optional leading whitespace.

    Returns the leading whitespace and the match against the rest of ``body``,
    or ``None``. Detection, renaming and sanitising all use this helper so they
    agree on which payload lines carry a generic speaker prefix.
    """
    rest = body.lstrip()
    match = GENERIC_SPEAKER_PREFIX_RE.match(rest)
    if match is None:
        return None
    return body[: len(body) - len(rest)], match


def match_echoed_voice_label(body: str) -> tuple[str, re.Match[str], str, str] | None:
    """Match a leading voice opening whose label is repeated as a ``Label:`` text prefix.

    ``<v Alice>Alice: text`` is the form a renamed ``Speaker N:`` prefix takes:
    the voice span carries the label for renaming and sanitising, the visible
    prefix keeps the name readable in players that do not show voice names.
    Returns the leading whitespace, the voice-opening match, the cleaned label
    and the cue text after the echoed prefix, or ``None``.
    """
    rest = body.lstrip()
    match = VOICE_OPENING_RE.match(rest)
    if match is None:
        return None
    label = parsing.clean_speaker_label(match.group("label"))
    after_opening = rest[match.end() :]
    if not label or not after_opening.startswith(label):
        return None
    separator = LABEL_ECHO_SEPARATOR_RE.match(after_opening, len(label))
    if separator is None:
        return None
    return body[: len(body) - len(rest)], match, label, after_opening[separator.end() :]


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
        generic_prefix = match_generic_speaker_prefix(stripped)
        if generic_prefix is not None:
            labels.add(parsing.clean_speaker_label(generic_prefix[1].group("label")))
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
        rewritten_line = replace_generic_speaker_prefix(line, None)
        rewritten_line = VOICE_OPENING_RE.sub("", replace_echoed_voice_label(rewritten_line, None))
        rewritten_line = VOICE_CLOSING_RE.sub("", rewritten_line)
        changed = changed or rewritten_line != line
        if not rewritten_line.strip():
            # A line that only held the speaker label is dropped: a blank line would end the cue.
            continue
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
    first_line_prefixed = False
    for index, line in enumerate(lines):
        prefixed_line = replace_generic_speaker_prefix(line, name)
        if prefixed_line != line:
            rewritten_lines.append(prefixed_line)
            changed = True
            first_line_prefixed = first_line_prefixed or index == 0
            continue
        rewritten_line, line_changed, line_has_voice_opening = set_payload_line_voice(line, name)
        rewritten_lines.append(rewritten_line)
        changed = changed or line_changed
        has_voice_opening = has_voice_opening or line_has_voice_opening
    if has_voice_opening or first_line_prefixed:
        return rewritten_lines, changed, True
    if not rewritten_lines:
        return rewritten_lines, False, False
    rewritten_lines[0] = f"{voice_opening(name)}{rewritten_lines[0]}"
    return rewritten_lines, True, True


def replace_echoed_voice_label(line: str, name: str | None) -> str:
    """Replace the echoed ``Label:`` of a ``<v Label>Label: text`` line with ``name``, or drop it for ``None``.

    The voice opening itself is left unchanged; callers rewrite or remove it.
    Lines without an echoed label are returned unchanged.
    """
    body, newline = split_line_ending(line)
    echoed_label = match_echoed_voice_label(body)
    if echoed_label is None:
        return line
    leading, match, _label, text = echoed_label
    echo = f"{name}: " if name is not None else ""
    return f"{leading}{match.group(0)}{echo}{text}{newline}"


def replace_generic_speaker_prefix(line: str, name: str | None) -> str:
    """Turn a leading ``Speaker N: text`` into ``<v Name>Name: text</v>``, or into ``text`` for ``None``.

    This treats a generic prefix in the suggestion path like a rename, so the
    old ``Speaker N:`` never stays visible next to an applied name and
    clearing a suggestion removes it like the voice label. Voice openings
    inside the text are set to ``name`` or dropped. Lines without a generic
    prefix are returned unchanged.
    """
    body, newline = split_line_ending(line)
    generic_prefix = match_generic_speaker_prefix(body)
    if generic_prefix is None:
        return line
    leading, match = generic_prefix
    text = match.group("text")
    if name is None:
        return f"{leading}{text}{newline}"
    text = VOICE_OPENING_RE.sub(lambda _match: voice_opening(name), text)
    return f"{leading}{voice_opening(name)}{name}: {text}</v>{newline}"


def set_payload_line_voice(line: str, name: str) -> tuple[str, bool, bool]:
    line_with_echo = replace_echoed_voice_label(line, name)
    rewritten_line, replacements = VOICE_OPENING_RE.subn(
        lambda _match: voice_opening(name),
        line_with_echo,
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
    """Rename ``<v label>`` voice openings and a leading ``Speaker N:`` prefix.

    A renamed voice opening keeps its classes. A renamed ``Speaker N:`` prefix
    becomes ``<v Name>Name: text</v>``: the voice span, closed on the same line
    so several prefixed lines in one cue do not nest, keeps the label
    detectable, renamable and sanitisable, and the echoed ``Name:`` keeps it
    visible in players that do not show voice names. Renaming such a line again
    replaces the echoed prefix together with the voice label instead of adding
    a second one. The line ending is kept.
    """
    body, newline = split_line_ending(line)

    def replace_voice_opening(match: re.Match[str]) -> str:
        label = parsing.clean_speaker_label(match.group("label"))
        target_label = mapping.get(label)
        if target_label is None:
            return match.group(0)
        return voice_opening(target_label, classes=match.group("classes"))

    generic_prefix = match_generic_speaker_prefix(body)
    echoed_label = match_echoed_voice_label(body)
    if generic_prefix is not None:
        leading, match = generic_prefix
        target_label = mapping.get(parsing.clean_speaker_label(match.group("label")))
        if target_label is not None:
            text = VOICE_OPENING_RE.sub(replace_voice_opening, match.group("text"))
            body = f"{leading}{voice_opening(target_label)}{target_label}: {text}</v>"
        else:
            body = VOICE_OPENING_RE.sub(replace_voice_opening, body)
    elif echoed_label is not None and echoed_label[2] in mapping:
        leading, match, label, text = echoed_label
        target_label = mapping[label]
        text = VOICE_OPENING_RE.sub(replace_voice_opening, text)
        body = f"{leading}{voice_opening(target_label, classes=match.group('classes'))}{target_label}: {text}"
    else:
        body = VOICE_OPENING_RE.sub(replace_voice_opening, body)

    rewritten_line = f"{body}{newline}"
    return rewritten_line, rewritten_line != line


def voice_opening(label: str, *, classes: str = "") -> str:
    return f"<v{classes} {label}>"
