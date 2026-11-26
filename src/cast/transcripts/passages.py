"""Small, canonical passage editor shared by the admin preview and services."""

from __future__ import annotations

from html import unescape
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.utils.html import strip_tags

from cast.file_replacement import StagedFileReplacementGroup

from . import dote, parsing, podlove, services, webvtt

if TYPE_CHECKING:
    from cast.models.transcript import Transcript


def get_passages(transcript: Transcript, *, vtt_content: str | None = None) -> list[dict[str, Any]]:
    """Read public artifacts only, preferring the web-player transcript."""
    data = transcript._load_transcript_json("podlove")
    podlove.validate_edit_times(data)
    rows = [
        {
            "start_ms": start,
            "text": str(segment.get("text", "")),
            "speaker": parsing.clean_speaker_label(segment.get("speaker") or segment.get("voice")),
        }
        for segment in data.get("transcripts", [])
        if isinstance(segment, dict) and (start := podlove.segment_start_ms(segment)) is not None
    ]
    if not rows:
        rows = [
            {
                "start_ms": start,
                "text": str(line.get("text", "")),
                "speaker": parsing.clean_speaker_label(line.get("speakerDesignation")),
            }
            for line in transcript.dote_data.get("lines", [])
            if isinstance(line, dict) and (start := dote.dote_timestamp_to_ms(line.get("startTime"))) is not None
        ]
    if not rows and transcript.vtt:
        current: dict[str, Any] | None = None
        if vtt_content is None:
            vtt_content = transcript._load_text_file("vtt")
        for line, start, payload in webvtt.cue_lines(vtt_content):
            if start is not None:
                current = {"start_ms": start, "text": "", "speaker": ""}
                rows.append(current)
            elif payload:
                if current is None:
                    raise ValidationError("This WebVTT passage has no supported timestamp.")
                voice = webvtt.VOICE_OPENING_RE.search(line)
                if voice:
                    current["speaker"] = parsing.clean_speaker_label(voice.group("label"))
                current["text"] = (
                    current["text"] + " " + parsing.clean_sample_text(unescape(strip_tags(line)))
                ).strip()
    starts = [row["start_ms"] for row in rows]
    if len(starts) != len(set(starts)):
        raise ValidationError("Passages have ambiguous start times. Replace the file and reload.")
    return sorted(rows, key=lambda row: row["start_ms"])


def change_speaker(transcript: Transcript, start_ms: int, speaker: str) -> None:
    """Change one passage in every stored format and retain its review decision."""
    services.validate_editor_artifacts(transcript)
    vtt_content = services.read_editor_webvtt(transcript)
    if start_ms not in {row["start_ms"] for row in get_passages(transcript, vtt_content=vtt_content)}:
        raise ValidationError("This passage no longer exists. Reload the transcript.")
    services.validate_speaker_destination_times(transcript, {start_ms}, vtt_content=vtt_content)
    expected = services.artifact_state(transcript)
    replacements = StagedFileReplacementGroup()
    try:
        names = {start_ms: speaker} if speaker else {}
        rejected = set() if speaker else {start_ms}
        if speaker:
            transcript._apply_suggestions_to_podlove(names, replacements=replacements)
            transcript._apply_suggestions_to_dote(names, replacements=replacements)
        else:
            transcript._clear_suggestions_from_podlove(rejected, replacements=replacements)
            transcript._clear_suggestions_from_dote(rejected, replacements=replacements)
        if vtt_content is not None:
            services.stage_webvtt_speaker_changes(transcript, vtt_content, names, rejected, replacements=replacements)
        sidecar = transcript.speakers_data
        changed = False
        for segment in sidecar.get("segments", []):
            if (
                isinstance(segment, dict)
                and (seconds := parsing.parse_timestamp_seconds(segment.get("start"))) is not None
                and round(seconds * 1000) == start_ms
            ):
                segment["editor_decision"] = {"action": "correct" if speaker else "reject", "speaker": speaker}
                changed = True
        if changed:
            transcript._write_speakers_data(sidecar, replacements=replacements)
        services.save_editor_artifacts(transcript, replacements, expected)
    except Exception:
        replacements.rollback()
        raise


def validate_text_destination(transcript: Transcript, start_ms: int, text: str) -> None:
    """Refuse partial corrections when uploaded formats do not match."""
    for name in ("podlove", "dote"):
        if getattr(transcript, name):
            data = transcript._load_transcript_json(name)
            starts = (
                [podlove.segment_start_ms(row) for row in data.get("transcripts", []) if isinstance(row, dict)]
                if name == "podlove"
                else [
                    dote.dote_timestamp_to_ms(row.get("startTime"))
                    for row in data.get("lines", [])
                    if isinstance(row, dict)
                ]
            )
            if starts.count(start_ms) != 1:
                raise ValidationError("Cannot update every file: check the passage timestamps.")
    if transcript.vtt:
        cues: list[list[str]] = []
        current: list[str] | None = None
        for line, start, payload in webvtt.cue_lines(transcript._load_text_file("vtt")):
            if start is not None:
                current = [] if start == start_ms else None
                if current is not None:
                    cues.append(current)
            elif payload:
                if current is not None:
                    current.append(line)
            else:
                current = None
        if len(cues) != 1 or webvtt.set_cue_text(cues[0], text) is None:
            raise ValidationError("Cannot update this WebVTT passage: check its timestamps and formatting.")


def correct_text(transcript: Transcript, start_ms: int, text: str) -> str:
    """Save a manual correction in canonical files and the existing glossary sidecar.

    Whitespace is folded to single spaces first, so every format (WebVTT cues are one
    line) stores the same text. Returns the stored text.
    """
    from . import corrections

    text = " ".join(text.split())
    if not text or len(text) > 100_000:
        raise ValidationError("Enter passage text (at most 100,000 characters).")
    rows = get_passages(transcript)
    if start_ms not in {row["start_ms"] for row in rows}:
        raise ValidationError("This passage no longer exists. Reload the transcript.")
    validate_text_destination(transcript, start_ms, text)
    data = transcript.corrections_data
    if not corrections._has_current_correction_data(data, transcript.mapping_fingerprint(), for_edit=True):
        data = corrections._fresh_data(transcript, [(row["start_ms"], row["text"]) for row in rows])
    data.setdefault("manual_texts", {})[str(start_ms)] = text
    corrections._write(transcript, data, {start_ms: text})
    return text
