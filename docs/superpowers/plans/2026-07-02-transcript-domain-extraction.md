# Transcript Domain Extraction Implementation Plan (H3/M9)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the WebVTT/Podlove/DOTe read-rewrite logic out of the 1575-line `Transcript` model into
per-format handler modules, move speaker-sample/voice-reference/known-speaker orchestration into services,
and replace the 150-line `transcript.edit` POST dispatcher with an action→handler map (findings H3 and M9 in
`backlog/2026-07-02-architecture-review.md`).

**Architecture:** New `src/cast/transcripts/` domain package. Pure, Django-free format modules
(`parsing`, `webvtt`, `podlove`, `dote`, `known_speakers`); model-facing orchestration in
`transcripts/services.py` (NO runtime import of `cast.models` — TYPE_CHECKING hints + related managers,
so `models/transcript.py` → `services` stays acyclic); view-facing editor orchestration in
`transcripts/editing.py` (imported only by views, may import models freely). `Transcript` keeps its full
public API as thin delegates; migrations untouched (the model class stays in `cast.models.transcript`).

**Behavior-preserving:** every moved function keeps its exact logic; file-IO primitives
(`_load_transcript_json`, `_save_*`, `podlove_data`, …, `StagedFileReplacementGroup` handling) stay on the
model; msgids, URL contracts, response shapes unchanged.

**Tech Stack:** Django 4.2–6, Wagtail 7, pytest, ruff (line length 119), mypy (django-stubs).

## Global Constraints

- Do NOT run `git commit` at any point during implementation tasks.
- 100% branch coverage; moved code keeps its existing tests (updated imports only where specified).
- Ruff + mypy clean.
- Pure format modules must not import Django or `cast.models`.

## External surface (verified 2026-07-02; final contract after Task 2)

- KEPT — `cast.models` re-exports: `Transcript`, `TranscriptSpeakerMapping`, `TranscriptSpeakerSample`,
  `TranscriptVoiceReferenceCandidate`.
- KEPT — `cast.models.transcript` public module-level names: `time_to_seconds`, `convert_segments`,
  `convert_dote_to_podcastindex_transcript`, `KNOWN_SPEAKER_DECISION_{APPROVE,CORRECT,REJECT}`,
  `KNOWN_SPEAKER_EDITOR_DECISION_FIELD`, `TRANSCRIPT_SPEAKER_MAPPING_ARTIFACT_FIELDS`.
- MIGRATED AND REMOVED (deliberate; underscore-private, zero references remained after Task 2's caller
  cleanup, sibling repos verified clean): module-level `_dote_timestamp_to_ms`/`_webvtt_timestamp_to_ms`
  (now `cast.transcripts.dote.dote_timestamp_to_ms` / `cast.transcripts.webvtt.webvtt_timestamp_to_ms`)
  and the `Transcript._clean_*`/`_parse_*`/`_format_*`/`_normalize_*`/webvtt-content classmethod aliases
  (now module functions in `cast.transcripts.{parsing,webvtt,known_speakers,voice_references}`).
  Task 1 kept temporary aliases so its own step could land without caller edits; Task 2 repointed every
  caller (`forms.py`, `views/transcript.py`, tests) and pruned the aliases with per-name grep evidence.
- Public `Transcript` methods used by views/voxhelm: `sync_speaker_mappings`,
  `apply_known_speaker_suggestions`, `save_known_speaker_editor_decisions`,
  `get_known_speaker_editor_decisions`, `get_speaker_suggestions`, `get_speaker_suggestion_summary`,
  `has_uncertain_speaker_suggestions`, `known_speaker_review_summary`, `get_speaker_labels`,
  `get_speaker_samples`, `get_voice_reference_candidates`, `rewrite_speaker_labels`,
  `transcript_artifact_fingerprint`, data properties.

---

### Task 1: Pure format/parsing modules

**Files:** create `src/cast/transcripts/{__init__,parsing,webvtt,podlove,dote,known_speakers}.py`;
modify `src/cast/models/transcript.py` (delegate + re-export; keep ALL class aliases so no caller changes).

- [ ] `parsing.py`: clean_sample_text, clean_speaker_label, normalize_sample_text, sample_text_is_useful,
      truncate_sample_text, parse_timestamp_seconds, parse_timestamp_decimal_seconds,
      parse_record_start_seconds, parse_record_decimal_seconds, quantize_seconds, format_decimal_timestamp,
      format_sample_timestamp, segment_sort_key, LOW_SIGNAL_TRANSCRIPT_SAMPLE_TEXTS
- [ ] `webvtt.py`: regexes + TIMING_SEPARATOR, webvtt_timestamp_to_ms, timing_line_start_ms,
      get_speaker_labels, apply/clear suggestions on content, cue-voice set/clear helpers, rewrite_speakers
- [ ] `podlove.py`: apply_suggestions, clear_suggestions, rewrite_speakers (pure data transforms)
- [ ] `dote.py`: dote_timestamp_to_ms, apply/clear/rewrite, time_to_seconds, convert_segments,
      convert_dote_to_podcastindex_transcript
- [ ] `known_speakers.py`: KNOWN_SPEAKER_* constants, normalize_editor_decision,
      segment_has_reject_decision, resolve_display_names (smoothing)
- [ ] Model methods become thin wrappers (load → pure transform → write); class aliases + module re-exports
      preserve every externally-used name; full suite green unchanged

### Task 2: Samples/voice-reference/services extraction + caller cleanup

**Files:** create `src/cast/transcripts/{speaker_samples,voice_references,services}.py`; modify
`src/cast/models/transcript.py`, `src/cast/forms.py`, `src/cast/views/transcript.py`; update tests that
poke `Transcript._*` to import the new module functions.

- [ ] `speaker_samples.py`: TranscriptSpeakerSample + candidate dataclass, per-format candidate extraction
      (takes parsed data), sort/spread/select; constants
- [ ] `voice_references.py`: TranscriptVoiceReferenceCandidate + segment dataclass, run building from
      podlove data, candidate derivation/ranking; constants
- [ ] `services.py`: sync_speaker_mappings, apply_known_speaker_suggestions,
      save_known_speaker_editor_decisions, rewrite_speaker_labels, get_speaker_labels, get_speaker_samples,
      get_voice_reference_candidates — NO runtime `cast.models` import (TYPE_CHECKING + related managers)
- [ ] `Transcript` methods become one-line delegates; dataclasses re-exported from `cast.models.transcript`
- [ ] forms.py/views use `cast.transcripts.{parsing,known_speakers}` directly; unreferenced class aliases
      dropped; tests updated; full suite green

### Task 3: Declarative edit dispatcher + editing service (M9)

**Files:** create `src/cast/transcripts/editing.py`; modify `src/cast/views/transcript.py`,
`src/cast/views/voxhelm.py`; tests as needed.

- [ ] Move view orchestration into `editing.py`: get_speaker_mapping_context, resolve_voice_reference_contributor,
      get_duplicate_voice_reference, get_voice_reference_candidate, create_voice_reference_from_candidate,
      episode_from_latest_revision (single copy; voxhelm imports it too)
- [ ] Replace the five-way `request.POST.get("action")` if/elif chain with an action→handler map; each
      handler returns an HttpResponse or None (fall through to render); identical messages/redirects/contexts
- [ ] Full suite green; ruff + mypy clean

### Task 4: Docs, release notes, backlog, gates (controller)

- [ ] Release note in `docs/releases/0.2.62.rst`; H3 fixed + M9 fixed annotations in the review doc;
      BACKLOG.md item resolved
- [ ] `just check` (100% branch coverage) + pi-review-loop until CLEAN; sibling-repo check (no template/URL
      contract changes expected); commit with "# "-prefixed messages

## Verification (after all tasks)

1. `just check`; 2. pi-review-loop CLEAN (max 3 rounds); 3. grep confirms no runtime import cycles
   (`cast.transcripts.services` imports no `cast.models` at runtime; pure modules import no Django);
   4. `views/voxhelm.py` and `views/transcript.py` share one `episode_from_latest_revision`.
