"""Apply the transcript glossary to stored transcripts.

Corrections live in the private ``Transcript.corrections`` sidecar (JSON)::

    {"version": 1, "source_fingerprint", "episode_id", "glossary_fingerprint",
     "segments": [{"start_ms", "raw_text",
                   "replacements": [{"start", "end", "from", "to", "source", "state"}]}],
     "proposals": [{"start_ms", "start", "end", "original", "to", "source", "score", "state"}],
     "decisions": [{"original", "to", "state"}],
     "occurrence_decisions": [{"start_ms", "start", "end", "from", "to", "source", "score", "state"}]}

``raw_text`` is the Podlove segment text as received; the public Podlove, DOTe and
WebVTT text is always derived from it plus the replacements that are not rejected,
matched by ``start_ms``. Speaker fields are never touched, so known-speaker
application and corrections can run in any order.

Editor input is stored as data and never inferred from what the glossary finds:
``decisions`` hold transcript-wide decisions per (normalised original, target) and
``occurrence_decisions`` per occurrence, keyed by (start_ms, start, end, from, to);
both are ``approved`` or ``rejected`` and the latest action wins. ``replacements``
and ``proposals`` are recomputed on every refresh (see ``_build``).

The functions below are what the transcript review calls; each one persists the
sidecar and re-applies the corrections.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from django.core.exceptions import ValidationError
from django.db import models, router, transaction
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from wagtail.blocks import Block, CharBlock, StreamValue, StructValue, URLBlock
from wagtail.models import Page
from wagtail.rich_text import RichText

from cast.file_replacement import StagedFileReplacementGroup
from cast.media_derivation import save_transcript_with_derivations

from ..models import Contributor, Episode, Podcast, Transcript, TranscriptGlossaryTerm, get_podcast_transcript_language
from . import dote, podlove, services, webvtt
from .glossary import (
    ContributorGlossary,
    EffectiveGlossary,
    Replacement,
    ShowTerm,
    TextSegment,
    apply_replacements,
    compile_phrase_pattern,
    episode_terms,
    find_proposals,
    find_replacements,
    normalize_phrase,
    parse_contributor_variants,
)

logger = logging.getLogger(__name__)

SIDECAR_VERSION = 1

STATE_AUTO = "auto"
STATE_APPROVED = "approved"
STATE_REJECTED = "rejected"
STATE_OPEN = "open"
DECISION_ACTIONS = (STATE_APPROVED, STATE_REJECTED)

SOURCE_DECISION = "decision"

STATUS_APPLIED = "applied"
STATUS_NEEDS_EPISODE = "needs_episode"
STATUS_NO_SEGMENTS = "no_segments"


def _save_derived_artifacts(transcript: Transcript, **kwargs: Any) -> None:
    kwargs["update_fields"] = [*kwargs["update_fields"], "source_fingerprint"]
    save_transcript_with_derivations(transcript, preserve_source_fingerprint=True, **kwargs)


@dataclass(frozen=True)
class CorrectionFormatChanges:
    """Counts of changed public text units in each format."""

    podlove: int = 0
    dote: int = 0
    vtt: int = 0


@dataclass(frozen=True)
class CorrectionsResult:
    """Outcome of a corrections run.

    ``status`` is ``applied``, ``needs_episode`` (no episode context: the review must
    ask the editor to choose one of ``episodes_using_audio``; nothing was replaced) or
    ``no_segments`` (no Podlove segments to correct). ``changed`` counts Podlove
    segments whose public text changed. ``format_changes`` also reports changed
    DOTe lines and WebVTT cues, including on dry runs.
    """

    status: str
    automatic: int = 0
    approved: int = 0
    proposals: int = 0
    changed: int = 0
    format_changes: CorrectionFormatChanges = field(default_factory=CorrectionFormatChanges)

    @property
    def needs_episode(self) -> bool:
        return self.status == STATUS_NEEDS_EPISODE


class GlossaryAddError(ValidationError):
    """``add_original_to_glossary`` cannot add the original (message is translatable)."""


@dataclass(frozen=True)
class CorrectionsEpisodeState:
    """The episode that supplies the glossary of a transcript's corrections.

    ``episode`` is the stored episode (or, before the first run, the one a run
    would pick); ``choices`` are the episodes using the audio; ``needs_choice`` is
    true when there is no usable episode, and ``stale`` when the stored one no
    longer uses the audio.
    """

    episode: Episode | None
    choices: list[Episode]
    needs_choice: bool
    stale: bool


@dataclass
class _State:
    data: dict[str, Any]
    episode: Episode | None
    previously_corrected: set[int] = field(default_factory=set)
    fresh: bool = False


# --- episode context -------------------------------------------------------------------------


def episodes_using_audio(transcript: Transcript) -> list[Episode]:
    """Episodes the review may offer as glossary context for this transcript."""
    return list(
        Episode.objects.using(transcript._state.db).filter(podcast_audio_id=transcript.audio_id).order_by("pk")
    )


def _uses_audio(episode: Episode | None, transcript: Transcript) -> bool:
    if episode is not None and episode._state.db != transcript._state.db:
        raise ValidationError(_("The episode belongs to a different database."))
    return episode is not None and episode.podcast_audio_id == transcript.audio_id


def _valid_episode_id(value: object) -> bool:
    return type(value) is int and value > 0


def _valid_episode_reference(data: dict[str, Any]) -> bool:
    return "episode_id" in data and (data["episode_id"] is None or _valid_episode_id(data["episode_id"]))


def _stored_episode(transcript: Transcript, data: dict[str, Any]) -> Episode | None:
    episode_id = data.get("episode_id")
    if not _valid_episode_id(episode_id):
        return None
    return (
        Episode.objects.using(transcript._state.db).filter(pk=episode_id, podcast_audio_id=transcript.audio_id).first()
    )


def corrections_episode_state(transcript: Transcript) -> CorrectionsEpisodeState:
    """Episode context of the corrections, for the review to show or ask for."""
    choices = episodes_using_audio(transcript)
    if corrections_are_current(transcript):
        episode_id = transcript.corrections_data["episode_id"]
        episode = next((choice for choice in choices if choice.pk == episode_id), None)
        stale = episode_id is not None and episode is None
    else:
        episode, stale = (choices[0] if len(choices) == 1 else None), False
    return CorrectionsEpisodeState(episode, choices, episode is None, stale)


def _initial_episode(transcript: Transcript, episode: Episode | None) -> Episode | None:
    """The given episode if it uses the audio, else the audio's only episode.

    The rule of ``cast.voxhelm.resolve_audio_episode``, which this package must not
    import (see ``tests/import_cycle_test.py``).
    """
    if _uses_audio(episode, transcript):
        return episode
    episodes = episodes_using_audio(transcript)
    return episodes[0] if len(episodes) == 1 else None


# --- effective glossary ----------------------------------------------------------------------


def _struct_links(value: StructValue) -> Iterator[str]:
    """A paragraph with a link for each URL field of a struct block whose preceding field is a text field.

    Site blocks keep show-note links as plain fields ("title" and "url" of a link item,
    "sponsor_name" and "sponsor_url"); the text field declared right before the URL field
    is taken as the link text.
    """
    previous: tuple[str, Block] | None = None
    for name, block in value.block.child_blocks.items():
        if isinstance(block, URLBlock) and previous is not None and isinstance(previous[1], CharBlock):
            text, url = value.get(previous[0]), value.get(name)
            if isinstance(text, str) and text and isinstance(url, str) and url:
                yield format_html('<p><a href="{}">{}</a></p>', url, text)  # own block: no phrase spans two links
        previous = (name, block)


def _show_note_sources(value: Any) -> Iterator[str]:
    """HTML of the show notes in a StreamField value, in order: rich text and struct-block links."""
    if isinstance(value, RichText):
        if value.source:
            yield value.source
    elif isinstance(value, StreamValue):
        for child in value:
            yield from _show_note_sources(child.value)
    elif isinstance(value, StructValue):
        yield from _struct_links(value)
        for item in value.values():
            yield from _show_note_sources(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _show_note_sources(item)
    elif isinstance(value, Sequence) and not isinstance(value, str):
        for item in value:
            yield from _show_note_sources(item)


def _glossary_revision(episode: Episode) -> Episode:
    # Wagtail's revision deserializer otherwise resolves foreign keys on default.
    if episode.has_unpublished_changes and episode.latest_revision_id:
        revision = Episode.from_serializable_data(episode.latest_revision.content, check_fks=False)
        revision._state.db = episode._state.db
        return cast(Episode, revision)
    return episode


def effective_glossary(episode: Episode) -> tuple[EffectiveGlossary, str]:
    """The episode's glossary and a fingerprint of its input.

    Contributors are all contributors assigned to the episode, hidden ones
    included: their variants are private input and never published. Episode terms
    come from the show notes (rich text and struct-block links in ``body``) and the
    title. Like the speaker review, the latest revision is used, so draft show notes
    count.
    """
    revision = _glossary_revision(episode)
    contributors: list[ContributorGlossary] = []
    contributor_ids = list(dict.fromkeys(item.contributor_id for item in revision.contributor_assignments.all()))
    by_id = Contributor.objects.using(episode._state.db).in_bulk(contributor_ids)
    for contributor_id in contributor_ids:
        contributor = by_id.get(contributor_id)
        if contributor is None:
            continue
        contributors.append(ContributorGlossary(contributor.display_name, contributor.transcript_variants))
    podcast = Podcast.objects.using(episode._state.db).ancestor_of(episode).order_by("-depth").first()
    assert podcast is not None
    show_terms = [
        ShowTerm(term.term, term.variants)
        for term in TranscriptGlossaryTerm.objects.using(episode._state.db)
        .filter(podcast_id=podcast.pk)
        .order_by("pk")
    ]
    terms = episode_terms("\n".join(_show_note_sources(revision.body)), revision.title)
    language = get_podcast_transcript_language(podcast)
    payload = {
        "episode_id": episode.pk,
        "latest_revision_id": episode.latest_revision_id,
        "has_unpublished_changes": episode.has_unpublished_changes,
        "contributors": [[item.display_name, item.transcript_variants] for item in contributors],
        "show_terms": [[item.term, item.variants] for item in show_terms],
        "episode_terms": terms,
        "language": language,
    }
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return EffectiveGlossary(contributors, show_terms, terms, language=language), fingerprint


# --- sidecar ---------------------------------------------------------------------------------


def _valid_segment_starts(segments: list[Any]) -> bool:
    seen: set[int] = set()
    for segment in segments:
        start_ms = podlove.parse_start_ms(segment.get("start_ms")) if isinstance(segment, dict) else None
        if start_ms is None or start_ms in seen:
            return False
        seen.add(start_ms)
    return True


def _has_current_correction_data(data: dict[str, Any], fingerprint: str, *, for_edit: bool = False) -> bool:
    segments = data.get("segments")
    if (
        data.get("version") != SIDECAR_VERSION
        or data.get("source_fingerprint") != fingerprint
        or not isinstance(segments, list)
    ):
        return False
    if not _valid_segment_starts(segments):
        if for_edit:
            raise ValidationError(_("Saved corrections have invalid or duplicate segment start times."))
        return False
    return (
        all(
            isinstance(segment.get("raw_text"), str) and isinstance(segment.get("replacements"), list)
            for segment in segments
        )
        and isinstance(data.get("proposals"), list)
        and isinstance(data.get("decisions"), list)
        and isinstance(data.get("occurrence_decisions"), list)
    )


def _is_current(data: dict[str, Any], fingerprint: str, *, for_edit: bool = False) -> bool:
    return _has_current_correction_data(data, fingerprint, for_edit=for_edit) and _valid_episode_reference(data)


def corrections_are_current(transcript: Transcript) -> bool:
    """Whether the stored corrections belong to the transcript's current artifacts."""
    return _is_current(transcript.corrections_data, transcript.source_fingerprint)


def _fresh_data(transcript: Transcript, texts: Iterable[tuple[int, str]]) -> dict[str, Any]:
    return {
        "version": SIDECAR_VERSION,
        "source_fingerprint": transcript.mapping_fingerprint(),
        "episode_id": None,
        "glossary_fingerprint": "",
        "segments": [{"start_ms": start_ms, "raw_text": text, "replacements": []} for start_ms, text in texts],
        "proposals": [],
        "decisions": [],
        "occurrence_decisions": [],
    }


def _start_counts(records: object, get_start: Callable[[dict[str, Any]], int | None]) -> Counter[int]:
    if not isinstance(records, list):
        return Counter()
    return Counter(start for row in records if isinstance(row, dict) and (start := get_start(row)) is not None)


def _admit_correction_artifacts(transcript: Transcript) -> tuple[dict[str, Any], Counter[int]]:
    services.validate_editor_artifacts(transcript)
    data = transcript._load_transcript_json("podlove")
    podlove.validate_edit_times(data)
    counts = _start_counts(data.get("transcripts"), podlove.segment_start_ms)
    if any(count > 1 for count in counts.values()):
        raise ValidationError(_("Podlove has ambiguous start times. Replace the artifact and reload."))
    return data, counts


def _load_state(transcript: Transcript, *, episode: Episode | None = None) -> _State | CorrectionsResult:
    """The current sidecar, or a fresh one with the current Podlove text as raw text.

    A sidecar written for other artifacts (new Voxhelm import or upload) is
    replaced; its decisions are not carried over.
    """
    _uses_audio(episode, transcript)
    podlove_data = _admit_correction_artifacts(transcript)[0]
    data = transcript.corrections_data
    if _has_current_correction_data(data, transcript.mapping_fingerprint(), for_edit=True):
        previously = {segment["start_ms"] for segment in data["segments"] if segment["replacements"]}
        context = (
            _stored_episode(transcript, data)
            if _valid_episode_reference(data)
            else _initial_episode(transcript, episode)
        )
        return _State(data, context, previously)
    texts = podlove.get_texts(podlove_data)
    if not texts:
        return CorrectionsResult(STATUS_NO_SEGMENTS)
    return _State(_fresh_data(transcript, texts), _initial_episode(transcript, episode), fresh=True)


_REPLACEMENT_FIELDS = ("start", "end", "from", "to", "source", "state")
_PROPOSAL_FIELDS = ("start_ms", "start", "end", "to", "source", "score", "state")


def _occurrence_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (item["start_ms"], item["start"], item["end"], item["from"], item["to"])


def _build(data: dict[str, Any], episode: Episode) -> dict[str, Any]:
    """Recompute replacements and proposals from raw text and the stored decisions.

    Candidates are the glossary's automatic matches, occurrences of approved
    transcript-wide decisions, occurrences with an approved occurrence decision
    (raw text never changes within a sidecar) and the glossary's proposals. A
    candidate's state is its occurrence decision, else the decision for its
    (normalised original, target), else ``auto`` (automatic match) or ``open``
    (proposal). Approved candidates are applied first, occurrence decisions before
    transcript-wide ones, then automatic ones; a candidate overlapping an applied one
    is dropped. Rejected candidates are listed and never applied. Automatic
    candidates are listed under ``replacements``, all others under ``proposals``;
    applied ones of those are listed under ``replacements`` too.
    """
    glossary, glossary_fingerprint = effective_glossary(episode)
    segments = [TextSegment(segment["start_ms"], segment["raw_text"]) for segment in data["segments"]]
    raw = {segment.start_ms: segment.text for segment in segments}
    occurrence_decisions = [
        item for item in data["occurrence_decisions"] if podlove.parse_start_ms(item["start_ms"]) in raw
    ]
    occurrences = {_occurrence_key(item): item for item in occurrence_decisions}
    decisions = {(normalize_phrase(item["original"]), item["to"]): item for item in data["decisions"]}
    candidates: dict[tuple[Any, ...], dict[str, Any]] = {}
    applied: dict[int, list[tuple[int, int]]] = defaultdict(list)

    def add(
        start_ms: int, start: int, end: int, original: str, to: str, source: str, score: float, auto: bool
    ) -> None:
        key = (start_ms, start, end, original, to)
        if key in candidates:
            return
        decision = occurrences.get(key) or decisions.get((normalize_phrase(original), to))
        state = decision["state"] if decision else STATE_AUTO if auto else STATE_OPEN
        candidates[key] = {
            "start_ms": start_ms,
            "start": start,
            "end": end,
            "from": original,
            "to": to,
            "source": source,
            "score": score,
            "state": state,
            "automatic": auto,
            "applied": False,
        }

    def apply_in_order(items: Iterable[dict[str, Any]]) -> None:
        groups: dict[tuple[bool, bool, int], list[dict[str, Any]]] = defaultdict(list)
        for item in items:
            if item["state"] in (STATE_APPROVED, STATE_AUTO):
                priority = (item["state"] != STATE_APPROVED, _occurrence_key(item) not in occurrences)
                groups[(*priority, item["start_ms"])].append(item)

        for (_automatic, _transcript_wide, start_ms), group in sorted(groups.items()):
            spans = applied[start_ms]
            accepted: list[tuple[int, int]] = []
            earlier = 0
            # Both sequences are in text order. Once a previous span ends at
            # or before this start it cannot overlap any later candidate.
            for item in sorted(group, key=_occurrence_key):
                start, end = item["start"], item["end"]
                while earlier < len(spans) and spans[earlier][1] <= start:
                    earlier += 1
                if (earlier < len(spans) and spans[earlier][0] < end) or (accepted and start < accepted[-1][1]):
                    del candidates[_occurrence_key(item)]
                    continue
                accepted.append((start, end))
                item["applied"] = True
            applied[start_ms] = sorted(spans + accepted)

    for auto in find_replacements(segments, glossary):
        add(auto.start_ms, auto.start, auto.end, auto.original, auto.to, auto.source, 1.0, True)
    for item in occurrences.values():
        start_ms, start, end, original, to = _occurrence_key(item)
        if item["state"] == STATE_APPROVED and raw[start_ms][start:end] == original:
            add(start_ms, start, end, original, to, item["source"], item["score"], False)
    for decision in decisions.values():
        if decision["state"] != STATE_APPROVED:
            continue
        pattern = compile_phrase_pattern(decision["original"])
        if pattern is None:
            continue
        for segment in segments:
            for match in pattern.finditer(segment.text):
                start, end = match.span()
                original = segment.text[start:end]
                if original != decision["to"]:
                    add(segment.start_ms, start, end, original, decision["to"], SOURCE_DECISION, 1.0, False)
    apply_in_order(list(candidates.values()))

    exclude = [
        Replacement(item["start_ms"], item["start"], item["end"], item["from"], item["to"], item["source"])
        for item in candidates.values()
        if item["applied"]
    ]
    known = set(candidates)
    for found in find_proposals(segments, glossary, glossary.language, exclude=exclude):
        add(found.start_ms, found.start, found.end, found.original, found.to, found.source, found.score, False)
    apply_in_order([item for key, item in candidates.items() if key not in known])

    by_start: dict[int, list[dict[str, Any]]] = {start_ms: [] for start_ms in raw}
    proposals: list[dict[str, Any]] = []
    for item in sorted(candidates.values(), key=lambda item: (item["start_ms"], item["start"], item["to"])):
        if item["automatic"] or item["applied"]:
            by_start[item["start_ms"]].append({field: item[field] for field in _REPLACEMENT_FIELDS})
        if not item["automatic"]:
            proposals.append({"original": item["from"], **{field: item[field] for field in _PROPOSAL_FIELDS}})
    return {
        **data,
        "episode_id": episode.pk,
        "glossary_fingerprint": glossary_fingerprint,
        "occurrence_decisions": occurrence_decisions,
        "segments": [
            {"start_ms": segment.start_ms, "raw_text": segment.text, "replacements": by_start[segment.start_ms]}
            for segment in segments
        ],
        "proposals": proposals,
    }


def corrected_texts(data: dict[str, Any], start_milliseconds: Iterable[int] | None = None) -> dict[int, str]:
    """Corrected text per ``start_ms``: manual text or raw text with non-rejected edits.

    Pure function of the sidecar data. Limited to ``start_milliseconds`` when given.
    """
    wanted = None if start_milliseconds is None else set(start_milliseconds)
    manual_texts = data.get("manual_texts", {})
    texts: dict[int, str] = {}
    for segment in data.get("segments", []):
        start_ms = segment["start_ms"]
        if wanted is not None and start_ms not in wanted:
            continue
        manual_key = str(start_ms)
        if manual_key in manual_texts:
            texts[start_ms] = manual_texts[manual_key]
            continue
        edits = [
            Replacement(start_ms, item["start"], item["end"], item["from"], item["to"], item["source"])
            for item in segment["replacements"]
            if item["state"] != STATE_REJECTED
        ]
        texts[start_ms] = apply_replacements(segment["raw_text"], edits)
    return texts


def _prepare_correction_destinations(
    transcript: Transcript, texts: dict[int, str], podlove_counts: Counter[int], dote_data: dict[str, Any]
) -> tuple[str, int]:
    """Check each destination and return the prepared WebVTT content and change count."""
    if not texts:
        return "", 0
    if transcript.podlove and texts.keys() - podlove_counts.keys():
        raise ValidationError(_("Correction destination has missing start times."))
    if transcript.dote:
        counts = _start_counts(dote_data.get("lines"), lambda line: dote.dote_timestamp_to_ms(line.get("startTime")))
        if any(counts[start] > 1 for start in texts):
            raise ValidationError(_("Correction destination has ambiguous start times."))
        if texts.keys() - counts.keys():
            raise ValidationError(_("Correction destination has missing start times."))
    if transcript.vtt:
        try:
            return webvtt.set_texts_in_content(transcript._load_text_file("vtt"), texts, require_all=True)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
    return "", 0


def _write(
    transcript: Transcript, data: dict[str, Any], texts: dict[int, str], *, dry_run: bool = False
) -> CorrectionFormatChanges:
    """Count changes after admission and stage the sidecar and public files on apply."""
    podlove_data, podlove_counts = _admit_correction_artifacts(transcript)
    dote_data = transcript._load_transcript_json("dote") if texts else {}
    vtt_content, cues_changed = _prepare_correction_destinations(transcript, texts, podlove_counts, dote_data)
    changes = CorrectionFormatChanges(
        podlove=podlove.set_texts(podlove_data, texts),
        dote=dote.set_texts(dote_data, texts),
        vtt=cues_changed,
    )
    if dry_run:
        return changes
    expected = services.artifact_state(transcript)
    if not transcript.source_fingerprint:
        transcript.mark_artifacts_received()
    changed_fields: list[str] = []
    replacements = StagedFileReplacementGroup()

    def save_with_current_glossary(instance: Transcript, **kwargs: Any) -> None:
        if _valid_episode_id(data.get("episode_id")):
            episode = _stored_episode(instance, data)
            if episode is None or effective_glossary(episode)[1] != data["glossary_fingerprint"]:
                raise services.TranscriptEditConflict("Reload the transcript; its glossary changed while editing.")
        _save_derived_artifacts(instance, **kwargs)

    try:
        if data != transcript.corrections_data:
            transcript._write_corrections_data(data, replacements=replacements)
            changed_fields.append("corrections")
        if changes.podlove:
            transcript._write_transcript_json("podlove", podlove_data, replacements=replacements)
            changed_fields.append("podlove")
        if changes.dote:
            transcript._write_transcript_json("dote", dote_data, replacements=replacements)
            changed_fields.append("dote")
        if changes.vtt:
            transcript._save_text_file("vtt", vtt_content, replacements=replacements)
            changed_fields.append("vtt")
        if changed_fields:
            services.save_editor_artifacts(transcript, replacements, expected, save=save_with_current_glossary)
    except Exception:
        replacements.rollback()
        transcript.source_fingerprint = expected["source_fingerprint"]
        raise
    if not changed_fields:
        transcript.source_fingerprint = expected["source_fingerprint"]
    return changes


def _current_episode(transcript: Transcript, episode: Episode | None) -> Episode | None:
    """Re-read the context episode, so the glossary fingerprint matches the commit-time check.

    Callers such as the Voxhelm import may hold an instance loaded long before; a
    draft saved since then must not look like a glossary change made while editing.
    """
    if episode is None:
        return None
    return (
        Episode.objects.using(transcript._state.db).filter(pk=episode.pk, podcast_audio_id=transcript.audio_id).first()
    )


def _commit(transcript: Transcript, state: _State, *, dry_run: bool = False) -> CorrectionsResult:
    state.episode = _current_episode(transcript, state.episode)
    if state.episode is None:
        if state.fresh and not dry_run:
            _write(transcript, state.data, {})  # keep the raw text before anything is applied
        return CorrectionsResult(STATUS_NEEDS_EPISODE)
    data = _build(state.data, state.episode)
    corrected = state.previously_corrected | {
        segment["start_ms"] for segment in data["segments"] if segment["replacements"]
    }
    corrected |= {int(start) for start in data.get("manual_texts", {})}
    texts = corrected_texts(data, corrected)
    changes = _write(transcript, data, texts, dry_run=dry_run)
    states = [item["state"] for segment in data["segments"] for item in segment["replacements"]]
    return CorrectionsResult(
        STATUS_APPLIED,
        automatic=states.count(STATE_AUTO),
        approved=states.count(STATE_APPROVED),
        proposals=sum(item["state"] == STATE_OPEN for item in data["proposals"]),
        changed=changes.podlove,
        format_changes=changes,
    )


def _update(transcript: Transcript, change: Callable[[dict[str, Any]], None]) -> CorrectionsResult:
    state = _load_state(transcript)
    if isinstance(state, CorrectionsResult):
        return state
    if state.episode is None:
        return CorrectionsResult(STATUS_NEEDS_EPISODE)
    change(state.data)
    return _commit(transcript, state)


# --- services --------------------------------------------------------------------------------


def refresh_transcript_corrections(
    transcript: Transcript, *, episode: Episode | None = None, dry_run: bool = False
) -> CorrectionsResult:
    """Recompute corrections with the current glossary and apply them.

    The first run (or the first after new artifacts were received) records the
    Podlove text as raw text and takes ``episode`` as context when it uses the
    audio, else the audio's only episode (``resolve_audio_episode``). Without an
    unambiguous episode the raw text is stored and nothing is replaced. Later runs
    use the stored episode; when it no longer uses the audio nothing changes. Both
    cases return ``needs_episode``. ``dry_run`` computes without writing.
    """
    state = _load_state(transcript, episode=episode)
    if isinstance(state, CorrectionsResult):
        return state
    return _commit(transcript, state, dry_run=dry_run)


def apply_transcript_corrections(transcript: Transcript) -> int:
    """Write the stored corrections into the public files without recomputing them.

    Rewrites segments with replacements or manual text and returns the number
    of Podlove segments whose text changed. Running it twice changes nothing.
    """
    data = transcript.corrections_data
    if not _is_current(data, transcript.source_fingerprint):
        return 0
    manual_texts = data.get("manual_texts", {})
    corrected = [
        segment["start_ms"]
        for segment in data["segments"]
        if segment["replacements"] or str(segment["start_ms"]) in manual_texts
    ]
    return _write(transcript, data, corrected_texts(data, corrected)).podlove


def set_corrections_episode(transcript: Transcript, episode: Episode) -> CorrectionsResult:
    """Store the editor's choice of episode context and re-apply the corrections."""
    if not _uses_audio(episode, transcript):
        raise ValidationError(_("The episode does not use this transcript's audio."))
    state = _load_state(transcript, episode=episode)
    if isinstance(state, CorrectionsResult):
        return state
    state.episode = episode
    return _commit(transcript, state)


def _set_decisions(data: dict[str, Any], originals: Iterable[str], to: str, action: str) -> None:
    chosen: dict[tuple[str, str], str] = {}
    for original in originals:
        chosen.setdefault((normalize_phrase(original), to), original)
    if not chosen:
        return

    decisions = [
        decision
        for decision in data["decisions"]
        if (normalize_phrase(decision["original"]), decision["to"]) not in chosen
    ]
    decisions.extend({"original": original, "to": to, "state": action} for original in chosen.values())
    data["decisions"] = decisions


def _check_action(action: str) -> None:
    if action not in DECISION_ACTIONS:
        raise ValueError(f"action must be one of {DECISION_ACTIONS}, not {action!r}")


def decide_correction_group(
    transcript: Transcript, to: str, action: str, originals: Iterable[str] | None = None
) -> CorrectionsResult:
    """Approve or reject the proposals for ``to`` transcript-wide.

    Each original (all of the group's, or only ``originals``) becomes a decision:
    approved originals are replaced everywhere in this transcript, also where they
    are found later; rejected ones are no longer proposed.
    """
    _check_action(action)

    def change(data: dict[str, Any]) -> None:
        chosen = (
            (item["original"] for item in data["proposals"] if item["to"] == to) if originals is None else originals
        )
        _set_decisions(data, chosen, to, action)

    return _update(transcript, change)


def _set_occurrence_decision(data: dict[str, Any], start_ms: int, item: dict[str, Any], action: str) -> None:
    decision = {
        "start_ms": start_ms,
        "start": item["start"],
        "end": item["end"],
        "from": item["from"],
        "to": item["to"],
    }
    decision |= {"source": item["source"], "score": item.get("score", 1.0), "state": action}
    key = _occurrence_key(decision)
    data["occurrence_decisions"] = [old for old in data["occurrence_decisions"] if _occurrence_key(old) != key]
    data["occurrence_decisions"].append(decision)


def decide_correction_occurrence(
    transcript: Transcript, *, start_ms: int, start: int, end: int, to: str, action: str
) -> CorrectionsResult:
    """Approve or reject one listed occurrence; the latest action on an occurrence wins.

    The occurrence may be listed as a proposal or as a replacement (automatic or
    approved, in any state), so a decision can always be changed again. Raises
    ``LookupError`` if nothing for ``to`` is listed at that position.
    """
    _check_action(action)

    def change(data: dict[str, Any]) -> None:
        listed = [{**item, "from": item["original"]} for item in data["proposals"]]
        for segment in data["segments"]:
            listed.extend({**item, "start_ms": segment["start_ms"]} for item in segment["replacements"])
        for item in listed:
            if (item["start_ms"], item["start"], item["end"], item["to"]) == (start_ms, start, end, to):
                _set_occurrence_decision(data, start_ms, item, action)
                return
        raise LookupError(f"nothing for {to!r} listed at {start_ms}:{start}:{end}")

    return _update(transcript, change)


def reject_automatic_replacement(
    transcript: Transcript, *, start_ms: int, start: int, end: int, to: str
) -> CorrectionsResult:
    """Reject one applied replacement (automatic or approved); it stays rejected on refresh.

    Raises ``LookupError`` if no replacement by ``to`` is applied at that position.
    """

    def change(data: dict[str, Any]) -> None:
        for segment in data["segments"]:
            for item in segment["replacements"]:
                position = (segment["start_ms"], item["start"], item["end"], item["to"])
                if position == (start_ms, start, end, to) and item["state"] != STATE_REJECTED:
                    _set_occurrence_decision(data, start_ms, item, STATE_REJECTED)
                    return
        raise LookupError(f"no replacement by {to!r} at {start_ms}:{start}:{end}")

    return _update(transcript, change)


def add_original_to_glossary(transcript: Transcript, original: str, to: str) -> CorrectionsResult:
    """Approve ``original`` -> ``to`` and add it to the glossary.

    The original becomes a variant of the podcast's show term ``to``, else of the
    credited contributor whose name (or a part or replacement of it) is ``to``,
    else of a new show term ``to``. Raises ``GlossaryAddError`` (a ``ValidationError``
    with translatable messages) without an episode context or when model validation
    refuses the variant, for example a common word as a show-term variant.
    """
    state = _load_state(transcript)
    if isinstance(state, CorrectionsResult) or state.episode is None:
        raise GlossaryAddError(_("Choose the episode for this transcript's glossary first."))
    episode = state.episode
    podcast = Podcast.objects.using(episode._state.db).ancestor_of(episode).order_by("-depth").first()
    assert podcast is not None
    using = router.db_for_write(TranscriptGlossaryTerm, instance=podcast)
    with transaction.atomic(using=using):
        # Lock the concrete parent row before any glossary reads. UPDATE also
        # obtains SQLite's write lock without a deferred read-to-write upgrade.
        Page.objects.using(using).filter(pk=podcast.pk).update(title=models.F("title"))
        term = TranscriptGlossaryTerm.objects.using(using).filter(podcast_id=podcast.pk, term__iexact=to).first()
        contributor = None if term is not None else _contributor_for(episode, to)
        if contributor is not None:
            Contributor.objects.using(using).filter(pk=contributor.pk).update(
                transcript_variants=models.F("transcript_variants")
            )
            contributor.refresh_from_db(using=using)
            line = (
                original
                if normalize_phrase(to) == normalize_phrase(contributor.display_name)
                else f"{original} => {to}"
            )
            contributor.transcript_variants = "\n".join(filter(None, [contributor.transcript_variants.rstrip(), line]))
            _validated(contributor.clean)
            contributor.save(using=using, update_fields=["transcript_variants"])
        else:
            if term is None:
                term, _created = TranscriptGlossaryTerm.objects.using(using).get_or_create(
                    podcast=podcast, term__iexact=to, defaults={"term": to}
                )
            term.variants = "\n".join(filter(None, [term.variants.rstrip(), original]))
            _validated(term.full_clean)
            term.save(using=using)
        _set_decisions(state.data, (original,), to, STATE_APPROVED)
        return _commit(transcript, state)


def _validated(clean: Callable[[], None]) -> None:
    try:
        clean()
    except ValidationError as exc:
        raise GlossaryAddError(exc) from exc


def _contributor_for(episode: Episode, to: str) -> Contributor | None:
    revision = _glossary_revision(episode)
    key = normalize_phrase(to)
    matches: dict[int, Contributor] = {}
    exact: dict[int, Contributor] = {}
    for assignment in revision.contributor_assignments.all():
        contributor = Contributor.objects.using(episode._state.db).filter(pk=assignment.contributor_id).first()
        if contributor is None:
            continue
        targets = [
            contributor.display_name,
            *contributor.display_name.split(),
            *(
                replacement
                for _variant, replacement in parse_contributor_variants(
                    contributor.display_name, contributor.transcript_variants
                )
            ),
        ]
        if key == normalize_phrase(contributor.display_name):
            exact[contributor.pk] = contributor
        if key in {normalize_phrase(target) for target in targets}:
            matches[contributor.pk] = contributor
    matches = exact or matches
    if len(matches) > 1:
        raise GlossaryAddError(_("This contributor name is ambiguous; use a unique full name."))
    return next(iter(matches.values()), None)
