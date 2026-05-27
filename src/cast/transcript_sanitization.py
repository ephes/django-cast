from __future__ import annotations

import copy
import re
from typing import Any

from django.core.exceptions import ObjectDoesNotExist


PODLOVE_SPEAKER_FIELDS = ("speaker", "voice")
WEBVTT_TIMING_SEPARATOR = "-->"
WEBVTT_VOICE_SPAN_RE = re.compile(r"<v(?:\s+(?P<label>[^>]+))?>(?P<body>.*?)</v>")
WEBVTT_VOICE_OPENING_RE = re.compile(r"<v(?:\s+([^>]+))?>")
WEBVTT_GENERIC_SPEAKER_PREFIX_RE = re.compile(r"^(?P<label>Speaker\s+\d+)\s*:\s*(?P<text>.*)$", re.IGNORECASE)


def clean_speaker_label(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def public_speaker_labels_for_episode(episode: Any | None, *, audio: Any | None = None) -> set[str] | None:
    """Return public speaker labels for a live episode, or ``None`` without episode context."""
    if episode is None:
        return None

    from .models import Episode

    episode = getattr(episode, "specific", episode)
    if not isinstance(episode, Episode):
        return None
    if audio is not None and episode.podcast_audio_id != getattr(audio, "pk", None):
        return set()
    if not episode.live:
        return set()
    return {
        label
        for assignment in episode.visible_contributor_assignments
        if (label := clean_speaker_label(assignment.display_name))
    }


def public_speaker_labels_for_transcript(transcript: Any, *, episode: Any | None = None) -> set[str] | None:
    """Return labels allowed for ``transcript``, or ``None`` without a live public anchor.

    With explicit episode context, the episode is authoritative. Without it,
    infer from all live episodes using the transcript's audio. Public views
    should use ``strict_public_speaker_labels_for_transcript`` so missing live
    anchors expose no speaker labels.
    """
    audio = getattr(transcript, "audio", None)
    explicit_labels = public_speaker_labels_for_episode(episode, audio=audio)
    if explicit_labels is not None:
        return explicit_labels

    episodes = getattr(audio, "episodes", None)
    if episodes is None:
        return None
    try:
        live_episodes = list(
            episodes.filter(live=True)
            .prefetch_related("contributor_assignments__contributor", "contributor_assignments__link")
            .all()
        )
    except (AttributeError, TypeError, ValueError):
        return None
    if not live_episodes:
        return None

    labels: set[str] = set()
    for live_episode in live_episodes:
        labels.update(public_speaker_labels_for_episode(live_episode, audio=audio) or set())
    return labels


def strict_public_speaker_labels_for_transcript(transcript: Any, *, episode: Any | None = None) -> set[str]:
    """Return labels allowed in public output, or an empty set without a live anchor."""
    return public_speaker_labels_for_transcript(transcript, episode=episode) or set()


def public_speaker_labels_for_audio(audio: Any, *, episode: Any | None = None) -> set[str] | None:
    explicit_labels = public_speaker_labels_for_episode(episode, audio=audio)
    if explicit_labels is not None:
        return explicit_labels
    try:
        transcript = audio.transcript
    except (AttributeError, ObjectDoesNotExist, ValueError):
        return None
    return public_speaker_labels_for_transcript(transcript)


def strict_public_speaker_labels_for_audio(audio: Any, *, episode: Any | None = None) -> set[str]:
    """Return labels allowed in public player output, or an empty set without a live anchor."""
    return public_speaker_labels_for_audio(audio, episode=episode) or set()


def public_episode_from_request(request: Any, *, transcript: Any) -> Any | None:
    episode_id = request.GET.get("episode_id")
    if episode_id is None:
        return None
    try:
        episode_id = int(episode_id)
    except (TypeError, ValueError):
        return None

    from .models import Episode

    audio = getattr(transcript, "audio", None)
    return (
        Episode.objects.filter(pk=episode_id, live=True, podcast_audio=audio)
        .prefetch_related("contributor_assignments__contributor", "contributor_assignments__link")
        .first()
    )


def sanitize_podlove_data(data: dict[str, Any], allowed_speaker_labels: set[str] | None) -> dict[str, Any]:
    if allowed_speaker_labels is None:
        return data

    sanitized = copy.deepcopy(data)
    transcripts = sanitized.get("transcripts", [])
    if not isinstance(transcripts, list):
        return sanitized

    for segment in transcripts:
        if not isinstance(segment, dict):
            continue
        for field_name in PODLOVE_SPEAKER_FIELDS:
            label = clean_speaker_label(segment.get(field_name))
            if label and label not in allowed_speaker_labels:
                segment.pop(field_name, None)
    return sanitized


def sanitize_dote_data(data: dict[str, Any], allowed_speaker_labels: set[str] | None) -> dict[str, Any]:
    if allowed_speaker_labels is None:
        return data

    sanitized = copy.deepcopy(data)
    lines = sanitized.get("lines", [])
    if not isinstance(lines, list):
        return sanitized

    for line in lines:
        if not isinstance(line, dict):
            continue
        label = clean_speaker_label(line.get("speakerDesignation"))
        if label and label not in allowed_speaker_labels:
            line["speakerDesignation"] = ""
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


def sanitize_webvtt_content(content: str, allowed_speaker_labels: set[str] | None) -> str:
    if allowed_speaker_labels is None:
        return content

    sanitized_lines = []
    in_cue_payload = False
    for line in content.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped:
            in_cue_payload = False
            sanitized_lines.append(line)
            continue
        if WEBVTT_TIMING_SEPARATOR in line:
            in_cue_payload = True
            sanitized_lines.append(line)
            continue
        if in_cue_payload:
            line = _sanitize_webvtt_payload_line(line, allowed_speaker_labels)
        sanitized_lines.append(line)
    return "".join(sanitized_lines)


def _sanitize_webvtt_payload_line(line: str, allowed_speaker_labels: set[str]) -> str:
    body = line.removesuffix("\r\n")
    newline = "\r\n" if body != line else ""
    if not newline:
        body = line.removesuffix("\n")
        newline = "\n" if body != line else ""

    def replace_voice_span(match: re.Match[str]) -> str:
        label = clean_speaker_label(match.group("label"))
        if label and label not in allowed_speaker_labels:
            return match.group("body")
        return match.group(0)

    body = WEBVTT_VOICE_SPAN_RE.sub(replace_voice_span, body)

    def replace_voice_opening(match: re.Match[str]) -> str:
        label = clean_speaker_label(match.group(1))
        if label and label not in allowed_speaker_labels:
            return ""
        return match.group(0)

    body = WEBVTT_VOICE_OPENING_RE.sub(replace_voice_opening, body)

    generic_prefix_match = WEBVTT_GENERIC_SPEAKER_PREFIX_RE.match(body)
    if generic_prefix_match is not None:
        label = clean_speaker_label(generic_prefix_match.group("label"))
        if label and label not in allowed_speaker_labels:
            body = generic_prefix_match.group("text")

    return f"{body}{newline}"
