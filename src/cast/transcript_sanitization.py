from __future__ import annotations

import copy
import re
from typing import Any

from django.core.exceptions import ObjectDoesNotExist

from .transcripts import dote, podlove, webvtt
from .transcripts.parsing import clean_speaker_label

PODLOVE_SPEAKER_FIELDS = ("speaker", "voice")


def audio_transcript_diarization_disabled(audio: Any | None) -> bool:
    return getattr(audio, "transcript_diarization_mode", "") == "disabled"


EDITOR_SPEAKER_PREVIEW_ATTR = "_cast_editor_speaker_preview"


def _episode_shows_speaker_labels(episode: Any) -> bool:
    """True for a live episode, or for a draft marked by ``editor_speaker_preview_episode``."""
    return bool(episode.live) or getattr(episode, EDITOR_SPEAKER_PREVIEW_ATTR, False) is True


def editor_speaker_preview_episode(page: Any, user: Any) -> Any | None:
    """Return the latest draft of an unpublished episode for an editor's speaker preview.

    Public speaker labels are limited to live episodes. An authenticated user who may
    edit an unpublished episode should still see the approved speaker names in its
    preview, so this returns the episode's latest revision (with its draft contributor
    assignments) marked to count as a speaker-label anchor. The marker lives only on
    this in-memory revision object; public, anonymous, and live-episode output is
    unchanged. Returns ``None`` for live pages, non-episodes, and users without edit
    permission. Callers must keep such responses out of shared caches.
    """
    from .models import Episode

    specific = getattr(page, "specific", page)
    if not isinstance(specific, Episode) or specific.live:
        return None
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    if not specific.permissions_for_user(user).can_edit():
        return None
    draft = specific.get_latest_revision_as_object()
    setattr(draft, EDITOR_SPEAKER_PREVIEW_ATTR, True)
    return draft


def _episode_is_publicly_visible(episode: Any) -> bool:
    """True when a live episode carries no Wagtail view restrictions.

    A view restriction (login, password, or group) means the episode is not
    public, so its speaker labels must never enter anonymous public output via
    the all-live-episodes aggregate fallback. Restriction *existence* is
    independent of the request, so this is a safe request-free filter; an
    explicitly anchored episode still flows through the authorized per-episode
    path elsewhere.
    """
    return not episode.get_view_restrictions().exists()


def public_speaker_labels_for_episode(episode: Any | None, *, audio: Any | None = None) -> set[str] | None:
    """Return public speaker labels for a live episode, or ``None`` without episode context."""
    if episode is None:
        return None
    if audio_transcript_diarization_disabled(audio):
        return set()

    from .models import Episode

    episode = getattr(episode, "specific", episode)
    if not isinstance(episode, Episode):
        return None
    if audio is not None and episode.podcast_audio_id != getattr(audio, "pk", None):
        return set()
    if not _episode_shows_speaker_labels(episode):
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
    if audio_transcript_diarization_disabled(audio):
        return set()
    explicit_labels = public_speaker_labels_for_episode(episode, audio=audio)
    if explicit_labels is not None:
        return explicit_labels | public_one_off_speaker_labels_for_transcript(transcript, episode=episode)

    episodes = getattr(audio, "episodes", None)
    if episodes is None:
        return None
    try:
        live_episodes = [
            episode
            for episode in episodes.filter(live=True)
            .prefetch_related("contributor_assignments__contributor", "contributor_assignments__link")
            .all()
            if _episode_is_publicly_visible(episode)
        ]
    except (AttributeError, TypeError, ValueError):
        return None
    if not live_episodes:
        return None

    labels: set[str] = set()
    for live_episode in live_episodes:
        labels.update(public_speaker_labels_for_episode(live_episode, audio=audio) or set())
    labels.update(public_one_off_speaker_labels_for_transcript(transcript))
    return labels


def strict_public_speaker_labels_for_transcript(transcript: Any, *, episode: Any | None = None) -> set[str]:
    """Return labels allowed in public output, or an empty set without a live anchor."""
    return public_speaker_labels_for_transcript(transcript, episode=episode) or set()


def public_speaker_labels_for_audio(audio: Any, *, episode: Any | None = None) -> set[str] | None:
    if audio_transcript_diarization_disabled(audio):
        return set()
    explicit_labels = public_speaker_labels_for_episode(episode, audio=audio)
    if explicit_labels is not None:
        try:
            transcript = audio.transcript
        except (AttributeError, ObjectDoesNotExist, ValueError):
            return explicit_labels
        return explicit_labels | public_one_off_speaker_labels_for_transcript(transcript, episode=episode)
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


def _public_episode_contexts_for_transcript(transcript: Any, *, episode: Any | None = None) -> list[Any] | None:
    from .models import Episode

    audio = getattr(transcript, "audio", None)
    if audio_transcript_diarization_disabled(audio):
        return []

    if episode is not None:
        episode = getattr(episode, "specific", episode)
        if not isinstance(episode, Episode):
            return []
        if getattr(episode, "podcast_audio_id", None) != getattr(audio, "pk", None):
            return []
        return [episode] if _episode_shows_speaker_labels(episode) else []

    episodes = getattr(audio, "episodes", None)
    if episodes is None:
        return None
    try:
        return [
            episode
            for episode in episodes.filter(live=True)
            .prefetch_related("contributor_assignments__contributor", "contributor_assignments__link")
            .all()
            if _episode_is_publicly_visible(episode)
        ]
    except (AttributeError, TypeError, ValueError):
        return None


def _current_mapping_rows(transcript: Any) -> list[Any]:
    try:
        fingerprint = transcript.mapping_fingerprint()
        rows = transcript.speaker_mappings.select_related("contributor").filter(
            active=True,
            review_state="approved",
            source_artifact_fingerprint=fingerprint,
        )
    except (AttributeError, TypeError, ValueError):
        return []
    return list(rows)


def _current_raw_speaker_labels(transcript: Any) -> set[str]:
    try:
        speaker_labels = transcript.get_speaker_labels()
    except (AttributeError, TypeError, ValueError):
        return set()
    return {label for speaker_label in speaker_labels if (label := clean_speaker_label(speaker_label))}


def _public_contributor_ids(episodes: list[Any]) -> set[int]:
    contributor_ids = set()
    for episode in episodes:
        for assignment in episode.visible_contributor_assignments:
            if assignment.contributor_id is not None:
                contributor_ids.add(assignment.contributor_id)
    return contributor_ids


def public_one_off_speaker_labels_for_transcript(transcript: Any, *, episode: Any | None = None) -> set[str]:
    episodes = _public_episode_contexts_for_transcript(transcript, episode=episode)
    if not episodes:
        return set()
    raw_speaker_labels = _current_raw_speaker_labels(transcript)
    return {
        label
        for row in _current_mapping_rows(transcript)
        if row.contributor_id is None
        and (label := clean_speaker_label(row.display_name))
        and label not in raw_speaker_labels
    }


def public_speaker_mapping_for_transcript(transcript: Any, *, episode: Any | None = None) -> dict[str, str]:
    """Return approved read-time speaker-label replacements for a public context."""
    episodes = _public_episode_contexts_for_transcript(transcript, episode=episode)
    if not episodes:
        return {}
    contributor_ids = _public_contributor_ids(episodes)
    raw_speaker_labels = _current_raw_speaker_labels(transcript)
    mapping: dict[str, str] = {}
    for row in _current_mapping_rows(transcript):
        source_label = clean_speaker_label(row.speaker_label)
        if not source_label:
            continue
        target_label = ""
        if row.contributor_id is not None:
            contributor = row.contributor
            if row.contributor_id in contributor_ids and contributor is not None and contributor.visible:
                target_label = clean_speaker_label(contributor.display_name)
        else:
            target_label = clean_speaker_label(row.display_name)
            if target_label in raw_speaker_labels:
                target_label = ""
        if target_label:
            mapping[source_label] = target_label
    return mapping


def apply_speaker_mapping_to_podlove_data(data: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    if not mapping:
        return data
    mapped = copy.deepcopy(data)
    if isinstance(mapped.get("transcripts", []), list):
        podlove.rewrite_speakers(mapped, mapping)
    return mapped


def apply_public_speaker_mapping_to_podlove_data(
    data: dict[str, Any], transcript: Any, *, episode: Any | None = None
) -> dict[str, Any]:
    return apply_speaker_mapping_to_podlove_data(
        data, public_speaker_mapping_for_transcript(transcript, episode=episode)
    )


def apply_speaker_mapping_to_dote_data(data: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    if not mapping:
        return data
    mapped = copy.deepcopy(data)
    if isinstance(mapped.get("lines", []), list):
        dote.rewrite_speakers(mapped, mapping)
    return mapped


def apply_public_speaker_mapping_to_dote_data(
    data: dict[str, Any], transcript: Any, *, episode: Any | None = None
) -> dict[str, Any]:
    return apply_speaker_mapping_to_dote_data(data, public_speaker_mapping_for_transcript(transcript, episode=episode))


def apply_speaker_mapping_to_webvtt_content(content: str, mapping: dict[str, str]) -> str:
    if not mapping:
        return content
    mapped_content, _changed = webvtt.rewrite_speakers(content, mapping)
    return mapped_content


def apply_public_speaker_mapping_to_webvtt_content(
    content: str, transcript: Any, *, episode: Any | None = None
) -> str:
    return apply_speaker_mapping_to_webvtt_content(
        content,
        public_speaker_mapping_for_transcript(transcript, episode=episode),
    )


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
            label = clean_speaker_label(segment.get(field_name))
            if label and label not in allowed_speaker_labels:
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
            label = clean_speaker_label(segment.get(field_name))
            if label and label not in allowed_speaker_labels:
                segment.pop(field_name, None)
    return sanitized


def sanitize_dote_data(data: dict[str, Any], allowed_speaker_labels: set[str] | None) -> dict[str, Any]:
    if allowed_speaker_labels is None:
        return data

    lines = data.get("lines", [])
    if not isinstance(lines, list):
        return data

    needs_sanitization = False
    for line in lines:
        if not isinstance(line, dict):
            continue
        label = clean_speaker_label(line.get("speakerDesignation"))
        if label and label not in allowed_speaker_labels:
            needs_sanitization = True
            break
    if not needs_sanitization:
        return data

    sanitized = copy.deepcopy(data)
    sanitized_lines = sanitized.get("lines", [])
    for line in sanitized_lines:
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
    # One entry per voice opening still open in the current cue: whether it was kept.
    open_voices: list[bool] = []
    for line in content.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped:
            in_cue_payload = False
            sanitized_lines.append(line)
            continue
        if webvtt.TIMING_SEPARATOR in line:
            in_cue_payload = True
            open_voices = []
            sanitized_lines.append(line)
            continue
        if in_cue_payload:
            line = _sanitize_webvtt_payload_line(line, allowed_speaker_labels, open_voices)
        sanitized_lines.append(line)
    return "".join(sanitized_lines)


def _sanitize_webvtt_payload_line(line: str, allowed_speaker_labels: set[str], open_voices: list[bool]) -> str:
    """Drop hidden voice labels from one cue payload line.

    Voice tags are matched with a stack shared by the lines of one cue, so a
    hidden voice's ``</v>`` is removed with its opening even when voice spans
    nest (``<v Ann>Ann: x <v Zed>y</v></v>``) or an opening-only voice is
    closed on a later line. A closing tag with no opening in the cue is kept.
    """
    body, newline = webvtt.split_line_ending(line)

    echoed_label = webvtt.match_echoed_voice_label(body)
    if echoed_label is not None:
        leading, match, label, text = echoed_label
        if label not in allowed_speaker_labels:
            # Drop the visible ``Name:`` echo; the voice tags are removed below.
            body = f"{leading}{match.group(0)}{text}"

    def replace_voice_tag(match: re.Match[str]) -> str:
        if match.group("opening") is not None:
            label = clean_speaker_label(match.group("label"))
            kept = not label or label in allowed_speaker_labels
            open_voices.append(kept)
            return match.group(0) if kept else ""
        if not open_voices or open_voices.pop():
            return match.group(0)
        return ""

    body = webvtt.VOICE_TAG_RE.sub(replace_voice_tag, body)

    generic_prefix = webvtt.match_generic_speaker_prefix(body)
    if generic_prefix is not None:
        leading, match = generic_prefix
        label = clean_speaker_label(match.group("label"))
        if label and label not in allowed_speaker_labels:
            body = f"{leading}{match.group('text')}"

    return f"{body}{newline}"
