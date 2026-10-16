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
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from functools import partial
from typing import Any, cast

from django.core.exceptions import ValidationError
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from wagtail.blocks import Block, CharBlock, StreamValue, StructValue, URLBlock
from wagtail.rich_text import RichText

from cast.file_replacement import StagedFileReplacementGroup
from cast.media_derivation import save_transcript_with_derivations

from ..models import Contributor, Episode, Transcript, TranscriptGlossaryTerm, get_podcast_transcript_language
from . import dote, podlove, webvtt
from .glossary import (
    ContributorGlossary,
    EffectiveGlossary,
    Replacement,
    ShowTerm,
    TextSegment,
    apply_replacements,
    episode_terms,
    find_proposals,
    find_replacements,
    normalize_phrase,
    parse_contributor_variants,
    phrase_spans,
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

_save_derived_artifacts = partial(save_transcript_with_derivations, preserve_source_fingerprint=True)


@dataclass(frozen=True)
class CorrectionsResult:
    """Outcome of a corrections run.

    ``status`` is ``applied``, ``needs_episode`` (no episode context: the review must
    ask the editor to choose one of ``episodes_using_audio``; nothing was replaced) or
    ``no_segments`` (no Podlove segments to correct). ``changed`` counts Podlove
    segments whose public text changed.
    """

    status: str
    automatic: int = 0
    approved: int = 0
    proposals: int = 0
    changed: int = 0

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
    return list(Episode.objects.filter(podcast_audio_id=transcript.audio_id).order_by("pk"))


def _uses_audio(episode: Episode | None, transcript: Transcript) -> bool:
    return episode is not None and episode.podcast_audio_id == transcript.audio_id


def _stored_episode(transcript: Transcript, data: dict[str, Any]) -> Episode | None:
    episode_id = data.get("episode_id")
    if not isinstance(episode_id, int):
        return None
    return Episode.objects.filter(pk=episode_id, podcast_audio_id=transcript.audio_id).first()


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


def effective_glossary(episode: Episode) -> tuple[EffectiveGlossary, str]:
    """The episode's glossary and a fingerprint of its input.

    Contributors are all contributors assigned to the episode, hidden ones
    included: their variants are private input and never published. Episode terms
    come from the show notes (rich text and struct-block links in ``body``) and the
    title. Like the speaker review, the latest revision is used, so draft show notes
    count.
    """
    revision = cast(Episode, episode.get_latest_revision_as_object())
    contributors: list[ContributorGlossary] = []
    seen: set[int] = set()
    for assignment in revision.contributor_assignments.all():
        if assignment.contributor_id in seen:
            continue
        seen.add(assignment.contributor_id)
        contributor = assignment.contributor
        contributors.append(ContributorGlossary(contributor.display_name, contributor.transcript_variants))
    podcast = episode.get_parent().specific
    show_terms = [
        ShowTerm(term.term, term.variants)
        for term in TranscriptGlossaryTerm.objects.filter(podcast_id=podcast.pk).order_by("pk")
    ]
    terms = episode_terms("\n".join(_show_note_sources(revision.body)), revision.title)
    language = get_podcast_transcript_language(podcast)
    payload = {
        "contributors": [[item.display_name, item.transcript_variants] for item in contributors],
        "show_terms": [[item.term, item.variants] for item in show_terms],
        "episode_terms": terms,
        "language": language,
    }
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return EffectiveGlossary(contributors, show_terms, terms, language=language), fingerprint


# --- sidecar ---------------------------------------------------------------------------------


def _is_current(data: dict[str, Any], fingerprint: str) -> bool:
    segments = data.get("segments")
    return (
        data.get("version") == SIDECAR_VERSION
        and data.get("source_fingerprint") == fingerprint
        and isinstance(segments, list)
        and all(
            isinstance(segment, dict)
            and isinstance(segment.get("start_ms"), int)
            and isinstance(segment.get("raw_text"), str)
            and isinstance(segment.get("replacements"), list)
            for segment in segments
        )
        and isinstance(data.get("proposals"), list)
        and isinstance(data.get("decisions"), list)
        and isinstance(data.get("occurrence_decisions"), list)
    )


def corrections_are_current(transcript: Transcript) -> bool:
    """Whether the stored corrections belong to the transcript's current artifacts."""
    return _is_current(transcript.corrections_data, transcript.source_fingerprint)


def _fresh_data(transcript: Transcript, texts: Iterable[tuple[int, str]]) -> dict[str, Any]:
    return {
        "version": SIDECAR_VERSION,
        "source_fingerprint": transcript.source_fingerprint,
        "episode_id": None,
        "glossary_fingerprint": "",
        "segments": [{"start_ms": start_ms, "raw_text": text, "replacements": []} for start_ms, text in texts],
        "proposals": [],
        "decisions": [],
        "occurrence_decisions": [],
    }


def _load_state(transcript: Transcript, *, episode: Episode | None = None) -> _State | CorrectionsResult:
    """The current sidecar, or a fresh one with the current Podlove text as raw text.

    A sidecar written for other artifacts (new Voxhelm import or upload) is
    replaced; its decisions are not carried over.
    """
    if not transcript.source_fingerprint:
        # Rows stored without ``save()``: record the current files as received, so the
        # corrections written below do not count as new artifacts on the next run.
        transcript.mark_artifacts_received()
        transcript.save(update_fields=["source_fingerprint"])
    data = transcript.corrections_data
    if _is_current(data, transcript.source_fingerprint):
        previously = {segment["start_ms"] for segment in data["segments"] if segment["replacements"]}
        return _State(data, _stored_episode(transcript, data), previously)
    texts = podlove.get_texts(transcript._load_transcript_json("podlove"))
    if not texts:
        return CorrectionsResult(STATUS_NO_SEGMENTS)
    return _State(_fresh_data(transcript, texts), _initial_episode(transcript, episode), fresh=True)


_REPLACEMENT_FIELDS = ("start", "end", "from", "to", "source", "state")
_PROPOSAL_FIELDS = ("start_ms", "start", "end", "to", "source", "score", "state")


def _occurrence_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (item["start_ms"], item["start"], item["end"], item["from"], item["to"])


def _overlaps(start: int, end: int, spans: Iterable[tuple[int, int]]) -> bool:
    return any(start < span_end and span_start < end for span_start, span_end in spans)


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
    occurrences = {_occurrence_key(item): item for item in data["occurrence_decisions"]}
    decisions = {(normalize_phrase(item["original"]), item["to"]): item for item in data["decisions"]}
    candidates: dict[tuple[Any, ...], dict[str, Any]] = {}
    applied: dict[int, list[tuple[int, int]]] = {start_ms: [] for start_ms in raw}

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
        def priority(item: dict[str, Any]) -> tuple[Any, ...]:
            key = _occurrence_key(item)
            return (item["state"] != STATE_APPROVED, key not in occurrences, key)

        for item in sorted(items, key=priority):
            if item["state"] not in (STATE_APPROVED, STATE_AUTO):
                continue
            spans = applied[item["start_ms"]]
            if _overlaps(item["start"], item["end"], spans):
                del candidates[_occurrence_key(item)]
                continue
            spans.append((item["start"], item["end"]))
            item["applied"] = True

    for auto in find_replacements(segments, glossary):
        add(auto.start_ms, auto.start, auto.end, auto.original, auto.to, auto.source, 1.0, True)
    for item in occurrences.values():
        start_ms, start, end, original, to = _occurrence_key(item)
        if item["state"] == STATE_APPROVED and raw[start_ms][start:end] == original:
            add(start_ms, start, end, original, to, item["source"], item["score"], False)
    for decision in decisions.values():
        if decision["state"] != STATE_APPROVED:
            continue
        for segment in segments:
            for start, end in phrase_spans(segment.text, decision["original"]):
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
        "segments": [
            {"start_ms": segment.start_ms, "raw_text": segment.text, "replacements": by_start[segment.start_ms]}
            for segment in segments
        ],
        "proposals": proposals,
    }


def corrected_texts(data: dict[str, Any], start_milliseconds: Iterable[int] | None = None) -> dict[int, str]:
    """Corrected text per ``start_ms``: raw text plus the replacements that are not rejected.

    Pure function of the sidecar data. Limited to ``start_milliseconds`` when given.
    """
    wanted = None if start_milliseconds is None else set(start_milliseconds)
    texts: dict[int, str] = {}
    for segment in data.get("segments", []):
        if wanted is not None and segment["start_ms"] not in wanted:
            continue
        edits = [
            Replacement(segment["start_ms"], item["start"], item["end"], item["from"], item["to"], item["source"])
            for item in segment["replacements"]
            if item["state"] != STATE_REJECTED
        ]
        texts[segment["start_ms"]] = apply_replacements(segment["raw_text"], edits)
    return texts


def _write(transcript: Transcript, data: dict[str, Any], texts: dict[int, str]) -> int:
    """Store the sidecar and the corrected public files in one staged replacement."""
    changed_fields: list[str] = []
    changed = 0
    replacements = StagedFileReplacementGroup()
    try:
        if data != transcript.corrections_data:
            transcript._write_corrections_data(data, replacements=replacements)
            changed_fields.append("corrections")
        podlove_data = transcript._load_transcript_json("podlove")
        changed = podlove.set_texts(podlove_data, texts)
        if changed:
            transcript._write_transcript_json("podlove", podlove_data, replacements=replacements)
            changed_fields.append("podlove")
        dote_data = transcript._load_transcript_json("dote")
        if dote.set_texts(dote_data, texts):
            transcript._write_transcript_json("dote", dote_data, replacements=replacements)
            changed_fields.append("dote")
        if transcript.vtt:
            content, cues = webvtt.set_texts_in_content(transcript._load_text_file("vtt"), texts)
            if cues:
                transcript._save_text_file("vtt", content, replacements=replacements)
                changed_fields.append("vtt")
        if changed_fields:
            replacements.save_model(transcript, update_fields=changed_fields, save=_save_derived_artifacts)
    except Exception:
        replacements.rollback()
        raise
    return changed


def _commit(transcript: Transcript, state: _State, *, dry_run: bool = False) -> CorrectionsResult:
    if state.episode is None:
        if state.fresh and not dry_run:
            _write(transcript, state.data, {})  # keep the raw text before anything is applied
        return CorrectionsResult(STATUS_NEEDS_EPISODE)
    data = _build(state.data, state.episode)
    corrected = state.previously_corrected | {
        segment["start_ms"] for segment in data["segments"] if segment["replacements"]
    }
    texts = corrected_texts(data, corrected)
    if dry_run:
        changed = podlove.set_texts(transcript._load_transcript_json("podlove"), texts)
    else:
        changed = _write(transcript, data, texts)
    states = [item["state"] for segment in data["segments"] for item in segment["replacements"]]
    return CorrectionsResult(
        STATUS_APPLIED,
        automatic=states.count(STATE_AUTO),
        approved=states.count(STATE_APPROVED),
        proposals=sum(item["state"] == STATE_OPEN for item in data["proposals"]),
        changed=changed,
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

    Rewrites the text of every segment that has replacements; returns the number
    of Podlove segments whose text changed. Running it twice changes nothing.
    """
    if not corrections_are_current(transcript):
        return 0
    data = transcript.corrections_data
    corrected = [segment["start_ms"] for segment in data["segments"] if segment["replacements"]]
    return _write(transcript, data, corrected_texts(data, corrected))


def set_corrections_episode(transcript: Transcript, episode: Episode) -> CorrectionsResult:
    """Store the editor's choice of episode context and re-apply the corrections."""
    if not _uses_audio(episode, transcript):
        raise ValidationError(_("The episode does not use this transcript's audio."))
    state = _load_state(transcript, episode=episode)
    if isinstance(state, CorrectionsResult):
        return state
    state.episode = episode
    return _commit(transcript, state)


def _set_decision(data: dict[str, Any], original: str, to: str, action: str) -> None:
    key = normalize_phrase(original)
    data["decisions"] = [
        decision
        for decision in data["decisions"]
        if (normalize_phrase(decision["original"]), decision["to"]) != (key, to)
    ]
    data["decisions"].append({"original": original, "to": to, "state": action})


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
        if originals is None:
            chosen = [item["original"] for item in data["proposals"] if item["to"] == to]
        else:
            chosen = list(originals)
        seen: set[str] = set()
        for original in chosen:
            if normalize_phrase(original) not in seen:
                seen.add(normalize_phrase(original))
                _set_decision(data, original, to, action)

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
    podcast = episode.get_parent().specific
    term = TranscriptGlossaryTerm.objects.filter(podcast_id=podcast.pk, term__iexact=to).first()
    contributor = None if term is not None else _contributor_for(episode, to)
    if contributor is not None:
        line = (
            original if normalize_phrase(to) == normalize_phrase(contributor.display_name) else f"{original} => {to}"
        )
        contributor.transcript_variants = "\n".join(filter(None, [contributor.transcript_variants.rstrip(), line]))
        _validated(contributor.clean)
        contributor.save(update_fields=["transcript_variants"])
    else:
        if term is None:
            term = TranscriptGlossaryTerm(podcast=podcast, term=to)
        term.variants = "\n".join(filter(None, [term.variants.rstrip(), original]))
        _validated(term.full_clean)
        term.save()
    _set_decision(state.data, original, to, STATE_APPROVED)
    return _commit(transcript, state)


def _validated(clean: Callable[[], None]) -> None:
    try:
        clean()
    except ValidationError as exc:
        raise GlossaryAddError(exc) from exc


def _contributor_for(episode: Episode, to: str) -> Contributor | None:
    revision = cast(Episode, episode.get_latest_revision_as_object())
    key = normalize_phrase(to)
    for assignment in revision.contributor_assignments.all():
        contributor = assignment.contributor
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
        if key in {normalize_phrase(target) for target in targets}:
            return Contributor.objects.get(pk=contributor.pk)
    return None
