"""Build the normalized, sanitized payload for the custom audio player.

This module is the single backend source of truth for the data the custom
(non-Podlove) web-component player consumes. It is deliberately **separate**
from :class:`cast.api.serializers.AudioPodloveSerializer` and is **not**
Podlove-compatible.

The returned ``PlayerPayload`` is a plain ``dict`` matching the TypeScript
``PlayerPayload`` shape used by ``javascript/src/audio/custom-player.ts``:

    {
      "audioId": int,
      "title": str,
      "subtitle": str,
      "duration": int | None,        # seconds; None until media metadata loads
      "poster": str,                 # "" if none
      "sources": [{"type": str, "src": str}, ...],
      "chapters": [{"start": int, "title": str}, ...],
      "transcript": {"url": str} | None,  # inline page payload (lazy)
                                          # the endpoint returns {"cues": [...]}
    }

The transcript is **lazy-loaded**: the inline page payload only carries a
``{"url"}`` (or ``None`` when there is no transcript), and the cues are built and
sanitized only when the player fetches that endpoint on first open. Transcript
cues always flow through the **public** sanitization path used by the serializer,
so non-public speaker labels and raw ``podlove_data`` never leak.
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any

from django.urls import reverse

from . import appsettings
from .transcript_sanitization import (
    apply_public_speaker_mapping_to_podlove_data,
    clean_speaker_label,
    sanitize_podlove_data,
    strict_public_speaker_labels_for_audio,
)

logger = logging.getLogger(__name__)

# Fixed source-format preference order (best first). Each entry maps an
# ``Audio`` file field name to the MIME ``type`` emitted to the player.
SOURCE_FORMATS: tuple[tuple[str, str], ...] = (
    ("m4a", "audio/mp4"),
    ("mp3", "audio/mpeg"),
    ("oga", "audio/ogg"),
    ("opus", "audio/opus"),
)

# Default ``end`` span (seconds) for a cue that has no usable end and no later
# cue to borrow a boundary from.
DEFAULT_CUE_SPAN_SECONDS = 5.0


def _finite_number(value: Any) -> float | None:
    """Return ``value`` as a finite float, or ``None``.

    Accepts ints/floats and plain numeric strings. ``bool`` is rejected
    (``isinstance(True, int)`` is ``True``) and clock strings are *not* parsed
    here (use :func:`_timestamp_seconds`).
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            number = float(stripped)
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def _clock_seconds(value: Any) -> float | None:
    """Parse an ``HH:MM:SS(.mmm)`` / ``MM:SS(.mmm)`` clock string to seconds."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped or ":" not in stripped:
        return None
    parts = stripped.split(":")
    if len(parts) not in (2, 3):
        return None
    try:
        seconds = float(parts[-1])
        minutes = int(parts[-2])
        hours = int(parts[-3]) if len(parts) == 3 else 0
    except ValueError:
        return None
    total = hours * 3600 + minutes * 60 + seconds
    return total if math.isfinite(total) else None


def _timestamp_seconds(value: Any) -> float | None:
    """Parse a cue timestamp that may be a clock string or a plain number."""
    clock = _clock_seconds(value)
    if clock is not None:
        return clock
    return _finite_number(value)


def parse_chapter_start_seconds(value: Any) -> int | None:
    """Parse a chapter ``start`` (``HH:MM:SS`` / ``MM:SS`` string) to int seconds."""
    seconds = _timestamp_seconds(value)
    if seconds is None or seconds < 0:
        return None
    return int(seconds)


def build_chapters(audio: Any) -> list[dict[str, Any]]:
    """Return ``[{"start": int_seconds, "title": str}, ...]`` for ``audio``.

    Rows with an unparseable ``start`` or an empty ``title`` are skipped and the
    skipped count is logged. ``href``/``image`` are intentionally omitted in v1.
    """
    chapters: list[dict[str, Any]] = []
    skipped = 0
    for chapter in audio.chapters:
        title = (chapter.get("title") or "").strip() if isinstance(chapter.get("title"), str) else ""
        start = parse_chapter_start_seconds(chapter.get("start"))
        if start is None or not title:
            skipped += 1
            continue
        chapters.append({"start": start, "title": title})
    if skipped:
        logger.info("cast player: skipped %d chapter(s) with unparseable start or empty title", skipped)
    return chapters


def build_sources(audio: Any, request: Any) -> list[dict[str, str]]:
    """Return one ``{"type", "src"}`` entry per present format, in preference order."""
    sources: list[dict[str, str]] = []
    for field_name, mime_type in SOURCE_FORMATS:
        field = getattr(audio, field_name, None)
        if field is None or not getattr(field, "name", ""):
            continue
        try:
            url = field.url
        except (ValueError, NotImplementedError):  # pragma: no cover - storage-backend dependent
            continue
        sources.append({"type": mime_type, "src": _absolute_uri(request, url)})
    return sources


def _absolute_uri(request: Any, url: str) -> str:
    if request is not None and hasattr(request, "build_absolute_uri"):
        return request.build_absolute_uri(url)
    return url


def _load_sanitized_segments(audio: Any, *, episode: Any) -> list[dict[str, Any]]:
    """Return public, sanitized Podlove transcript segments for ``audio``.

    Mirrors ``AudioPodloveSerializer``'s public path exactly: load the raw stored
    Podlove JSON, apply the read-time speaker mapping, then sanitize against the
    strict public speaker-label set. Raw ``podlove_data`` is never returned.
    """
    if not hasattr(audio, "transcript"):
        return []
    transcript = audio.transcript
    if not transcript.podlove:
        return []
    try:
        with transcript.podlove.open("r") as file:
            data = json.load(file)
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    data = apply_public_speaker_mapping_to_podlove_data(data, transcript, episode=episode)
    allowed_speaker_labels = strict_public_speaker_labels_for_audio(audio, episode=episode)
    data = sanitize_podlove_data(data, allowed_speaker_labels)
    segments = data.get("transcripts", [])
    return segments if isinstance(segments, list) else []


def _segment_speaker(segment: dict[str, Any]) -> str:
    for field_name in ("speaker", "voice"):
        label = clean_speaker_label(segment.get(field_name))
        if label:
            return label
    return ""


def build_cues(audio: Any, *, episode: Any, duration: int | None) -> list[dict[str, Any]]:
    """Return normalized transcript cues with a finite ``end > start`` for each.

    Defensive normalization (per the design spec):

    - ``start``: ``start_ms`` (→ seconds) preferred, else the ``start`` clock
      string. A cue without a finite ``start`` is skipped and counted.
    - ``text``: required; empty/whitespace cues are skipped and counted.
    - ``speaker``: the sanitized/mapped display label, else ``""``.
    - cues are sorted by ``start``.
    - ``end``: ``end_ms`` (→ seconds) preferred, else the ``end`` clock string.
      A missing/non-finite/``<= start`` end is synthesized from the next cue
      whose ``start`` is *strictly greater* (so same-start duplicates do not
      collapse the span); failing that, from ``duration`` (when finite and
      ``> start``) else ``start + 5``. The synthesized-end count is logged.
    """
    segments = _load_sanitized_segments(audio, episode=episode)

    skipped = 0
    collected: list[dict[str, Any]] = []
    for segment in segments:
        if not isinstance(segment, dict):
            skipped += 1
            continue
        start_ms = _finite_number(segment.get("start_ms"))
        start = start_ms / 1000.0 if start_ms is not None else _timestamp_seconds(segment.get("start"))
        text = segment.get("text")
        text = text.strip() if isinstance(text, str) else ""
        if start is None or not text:
            skipped += 1
            continue
        end_ms = _finite_number(segment.get("end_ms"))
        raw_end = end_ms / 1000.0 if end_ms is not None else _timestamp_seconds(segment.get("end"))
        collected.append(
            {
                "start": start,
                "raw_end": raw_end,
                "speaker": _segment_speaker(segment),
                "text": text,
            }
        )

    collected.sort(key=lambda cue: cue["start"])

    synthesized = 0
    cues: list[dict[str, Any]] = []
    finite_duration = float(duration) if isinstance(duration, (int, float)) and duration is not None else None
    for index, cue in enumerate(collected):
        start = cue["start"]
        end = cue["raw_end"]
        if end is None or not math.isfinite(end) or end <= start:
            synthesized += 1
            end = _synthesize_end(collected, index, start, finite_duration)
        cues.append(
            {
                "start": start,
                "end": end,
                "speaker": cue["speaker"],
                "text": cue["text"],
            }
        )

    if skipped:
        logger.info("cast player: skipped %d transcript cue(s) with missing start or empty text", skipped)
    if synthesized:
        logger.info("cast player: synthesized end for %d transcript cue(s)", synthesized)
    return cues


def _synthesize_end(collected: list[dict[str, Any]], index: int, start: float, finite_duration: float | None) -> float:
    """Return a finite end ``> start`` borrowed from the next strictly-later cue."""
    for later in collected[index + 1 :]:
        if later["start"] > start:
            return later["start"]
    if finite_duration is not None and finite_duration > start:
        return finite_duration
    return start + DEFAULT_CUE_SPAN_SECONDS


def audio_has_transcript(audio: Any) -> bool:
    """Cheap check: does this audio have a stored transcript file?

    Deliberately does **not** open/parse/sanitize the file. The inline payload
    path uses this so a detail-page render never builds or sanitizes the full
    transcript; cue normalization happens only in the lazy endpoint.
    """
    if not hasattr(audio, "transcript"):
        return False
    return bool(getattr(audio.transcript, "podlove", None))


def _fallback_transcript_url(audio: Any, *, post: Any, request: Any) -> str:
    url = reverse("cast:api:audio_player_transcript", kwargs={"pk": audio.pk})
    if post is not None and getattr(post, "pk", None) is not None:
        url = f"{url}?post_id={post.pk}"
    return _absolute_uri(request, url)


def audio_player_context_flags(*, enabled: bool) -> dict[str, bool]:
    """Return the asset/preconnect gate flags for the current player mode.

    ``enabled`` is the host's existing "this page has/uses audio" condition
    (``has_audio`` on detail, ``use_audio_player`` on list). These flags gate
    asset/preconnect includes only; player *rendering* is decided by the audio
    block template.
    """
    mode = appsettings.CAST_AUDIO_PLAYER
    return {
        "use_podlove_player": enabled and mode == "podlove",
        "use_custom_audio_player": enabled and mode == "custom",
    }


def build_player_payload(audio: Any, *, post: Any, request: Any, inline_transcript: bool = True) -> dict[str, Any]:
    """Return the normalized :class:`PlayerPayload` ``dict`` for ``audio``.

    The transcript is **lazy-loaded**: it is never inlined into the page.

    ``inline_transcript=True`` (the default, used by the inline ``json_script``)
    sets ``transcript`` to ``{"url": <endpoint>}`` when the audio has a transcript
    and ``None`` otherwise, **without building or sanitizing any cues** — that
    work is deferred to the endpoint so a detail-page render stays cheap.

    ``inline_transcript=False`` (used by the transcript endpoint) builds and
    sanitizes the cues and returns ``{"cues": [...]}``.
    """
    episode = getattr(post, "specific", post)

    duration: int | None = None
    if audio.duration is not None:
        duration = int(audio.duration.total_seconds())

    blog = None
    if post is not None:
        blog = getattr(getattr(post, "blog", None), "specific", None)
    poster = ""
    if episode is not None and hasattr(episode, "get_cover_image_poster_url"):
        poster = episode.get_cover_image_poster_url(request=request, blog=blog)

    transcript: dict[str, Any] | None
    if inline_transcript:
        if audio_has_transcript(audio):
            transcript = {"url": _fallback_transcript_url(audio, post=post, request=request)}
        else:
            transcript = None
    else:
        transcript = {"cues": build_cues(audio, episode=episode, duration=duration)}

    return {
        "audioId": audio.pk,
        "title": audio.title or audio.name or "",
        "subtitle": audio.subtitle or "",
        "duration": duration,
        "poster": poster or "",
        "sources": build_sources(audio, request),
        "chapters": build_chapters(audio),
        "transcript": transcript,
    }
