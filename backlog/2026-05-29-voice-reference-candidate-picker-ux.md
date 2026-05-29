# Voice Reference Candidate Picker UX

Status: implemented in django-cast 0.2.58. This note is retained as the
original shaping context; the shipped editor workflow is documented in
`docs/media/audio-and-transcripts.rst` and summarized in the 0.2.58 release
notes.

Related to: [Contributor Voice References](2026-05-28-contributor-voice-references.md),
[Speaker Diarization](2026-05-18-speaker-diarization.md), and
[Audio Transcript Diarization Mode](2026-05-27-audio-transcript-diarization-mode.md).

Prior-art operator runbook:
`../../django-chat/docs/contributors-and-diarization.md`, especially step 5,
which seeds `ContributorVoiceReference` rows from a shell helper that chooses a
long clean run in `Transcript.podlove_data`.

## Background

The private voice-reference storage slice has landed, and Voxhelm request
assembly can already use approved references for expected episode contributors.
The remaining editor problem is enrollment: creating the first source-range
reference for a new contributor still requires raw timecode entry.

That manual seconds flow is exactly the wrong UX for a podcast editor. The data
needed to propose better ranges often already exists: a diarized transcript has
speaker labels, text segments, and start/end timings. Editors should listen to
candidate passages and confirm identity, not hunt for seconds and type decimals
into an inline form.

## Current UI

### Contributor voice-reference storage

The Contributor snippet is defined in
[`src/cast/models/contributors.py`](../src/cast/models/contributors.py). Its
`panels` include an `InlinePanel("voice_references", label=_("Voice reference"))`
inside a private "Voice references" field group.

`ContributorVoiceReference` in the same file is an `Orderable` child object. Its
admin panels expose these fields directly:

- `clip`
- `source_audio`
- `source_episode`
- `start_seconds`
- `end_seconds`
- `status`
- `consent_confirmed`
- `allow_for_hidden_contributor`
- `notes`

That means a source-range reference is currently created by choosing an audio
object, typing decimal seconds into `start_seconds` and `end_seconds`, then
setting review state. The model validation is sound, but the editing surface is
manual:

- A reference must be either an uploaded `clip` or a source range, not both.
- A source range needs both bounds and `source_audio`.
- `start_seconds` must be before `end_seconds`.
- `status=APPROVED` requires `consent_confirmed=True`.

`ContributorVoiceReference.is_usable_for_voxhelm` only checks for
`Status.APPROVED`, while `ContributorVoiceReferenceQuerySet.usable_known_speaker()`
adds the contributor visibility rule. The Voxhelm request path in
[`src/cast/voxhelm.py`](../src/cast/voxhelm.py) then uses
`build_known_speaker_references()` to collect usable references from an episode's
assigned contributors and `build_known_speaker_reference_entry()` to serialize a
source range as:

```json
{
  "kind": "source_range",
  "audio": {"kind": "url", "url": "..."},
  "start": 123.456,
  "end": 153.456
}
```

The storage and request contract are therefore ready for good ranges. The gap is
how an editor finds and creates those ranges.

### Transcript edit page

The transcript edit view already has most of the admin UX needed for an audition
workflow.

[`src/cast/views/transcript.py`](../src/cast/views/transcript.py) builds the
speaker-mapping context:

- `get_speaker_mapping_context()` loads latest episode revisions for the
  transcript's audio, collects `visible_contributor_assignments`, and reads
  labels from `Transcript.get_speaker_labels()`.
- `get_speaker_mapping_rows()` combines each dynamic form field with samples
  from `Transcript.get_speaker_samples()`.
- `get_transcript_audio_sources()` exposes existing uploaded audio files as
  `<source>` entries with URL, MIME type, size, and title.
- `edit()` renders `speaker_mapping_rows`, `transcript_audio_sources`,
  `contributor_assignments`, and `known_speaker_review` into
  `cast/transcript/edit.html`.

[`src/cast/templates/cast/transcript/edit.html`](../src/cast/templates/cast/transcript/edit.html)
already renders:

- an `<audio controls preload="metadata" data-cast-speaker-audio>` element when
  transcript audio sources exist
- per-sample buttons with `data-cast-speaker-seek="{{ sample.start_seconds }}"`
- JavaScript that reads the data attribute, seeks the shared audio element, and
  calls `audio.play()`
- a "Map speakers to contributors" section with a form powered by
  `SpeakerContributorMappingForm`
- a "Known-speaker suggestions" review/apply panel when Voxhelm returned a
  private `Transcript.speakers` sidecar

[`src/cast/forms.py`](../src/cast/forms.py) defines
`SpeakerContributorMappingForm`. It dynamically creates one choice field per
speaker label and offers episode contributor assignments as choices. Its cleaned
`speaker_mapping` currently maps raw label to contributor display name for
`Transcript.rewrite_speaker_labels()`, not to a contributor id. That is enough
for the current label rewrite workflow, but a voice-reference creation action
needs the actual `Contributor` FK.

[`src/cast/models/transcript.py`](../src/cast/models/transcript.py) already
derives representative samples:

- `TranscriptSpeakerSample` carries text, a timestamp label, and start seconds.
- `get_speaker_labels()` extracts unique Podlove `speaker` / `voice` labels and
  DOTe `speakerDesignation` labels.
- `get_speaker_samples()` prefers Podlove segments, falls back to DOTe lines,
  filters low-information snippets, and spreads up to three samples across each
  label's appearances.
- `_get_podlove_speaker_sample_candidates()` parses segment text and start time
  from `start_ms`, `start`, or `startTime`.

This sample machinery helps identify speakers, but it does not yet find a
longest clean solo passage and it does not expose an end time or duration for a
candidate voice reference.

## Problem

For a new contributor, the editor has to leave the transcript-review context,
open the Contributor snippet, add a voice-reference inline row, and type source
range boundaries by hand. The person doing the work must already know which
audio file and decimal second bounds contain clean solo speech.

The sibling `django-chat` runbook works around this with an operator-only helper:
`longest_run(pd, name, cap=30.0, min_len=8.0)`. It scans
`t.podlove_data["transcripts"]`, finds the longest contiguous run whose
`speaker` matches the contributor name, caps it around 30 seconds, and creates
an approved `ContributorVoiceReference` with `source_audio`, `start_seconds`,
`end_seconds`, `status=APPROVED`, and `consent_confirmed=True`.

That proves the product direction, but it is not enough:

- it only exists in a runbook script, not django-cast product code
- it assumes labels have already been rewritten to contributor names
- it gives no admin audition affordance before creating the reference
- it uses direct shell/database creation instead of Wagtail permissions,
  validation, messages, and review UI
- it makes consent easy to satisfy in code, but the product UI must keep consent
  explicit

## Proposed UX

Add a voice-reference candidate picker to the transcript edit workflow. The
Contributor snippet should remain the place to inspect, disable, reject, or edit
existing private references, but it should not be the primary place where editors
discover source ranges.

Recommended placement: put the first implementation on the transcript edit page,
near "Map speakers to contributors". This page already knows the transcript,
audio, speaker labels, samples, referencing episodes, and contributor
assignments. It also already has the audio element and seek/play JavaScript.

Flow sketch:

1. The editor generates or uploads a diarized transcript.
2. The transcript edit page extracts speaker labels and shows the existing
   speaker-to-contributor mapping rows.
3. The editor maps `Speaker N` labels to contributor assignments, or the labels
   already match contributor display names from a previous mapping or
   known-speaker apply step.
4. A new "Voice-reference candidates" section groups candidate passages by
   resolved contributor.
5. Each candidate row shows contributor, raw speaker label, start/end timestamp,
   duration, a short transcript excerpt, and an audition button.
6. Clicking the audition button seeks the existing transcript audio and plays
   only that passage. A first slice can stop playback at the candidate end using
   the same shared audio element plus an end-time data attribute.
7. The editor confirms "this passage is this contributor" from the row.
8. The POST action creates a `ContributorVoiceReference` with:
   - `contributor` from the selected assignment, not from a display-name lookup
   - `source_audio=transcript.audio`
   - `source_episode` when there is one clear referencing episode, or the
     selected episode when the audio is reused
   - `start_seconds` and `end_seconds` from the candidate
   - `status=APPROVED` only when the editor explicitly confirms consent in the
     same flow
   - `consent_confirmed=True` only from an explicit consent checkbox or equivalent
     required approval control
9. If consent is not confirmed, either block the approved-create action or create
   a `PENDING` reference that the editor can later approve from the Contributor
   snippet. Do not silently mark consent true.

The confirmation should remain one operation after the editor has made the
required identity and consent choices. A useful shape is a per-row required
consent checkbox plus a disabled "Create approved reference" button until the
checkbox is checked. If that is too dense, split the first slice into "Save
pending reference from candidate" and a later approved-confirm flow.

## Candidate Derivation

Promote the runbook's `longest_run()` idea into product code, but make it a
reviewable candidate generator instead of an automatic creator.

Suggested helper shape:

```python
@dataclass(frozen=True)
class TranscriptVoiceReferenceCandidate:
    speaker_label: str
    start_seconds: Decimal
    end_seconds: Decimal
    duration_seconds: Decimal
    text: str
    rank: int
```

Possible API:

```python
Transcript.get_voice_reference_candidates(
    target_seconds=Decimal("30.000"),
    min_seconds=Decimal("8.000"),
    limit_per_speaker=3,
)
```

Candidate rules for the first slice:

- Use Podlove `transcripts` first because they already carry `start_ms`,
  `end_ms`, `speaker`, `voice`, and text in the code paths used today.
- Treat consecutive segments with the same clean speaker label as one candidate
  run when each segment has usable timing.
- Prefer longer runs up to a target cap around 30 seconds.
- Keep a minimum usable duration, initially around 8 seconds.
- Return several top candidates per speaker, not only one, so editors have a
  fallback when the top run contains cross-talk, music, laughter, or an edit.
- Reuse `Transcript._clean_sample_text()` and the low-information sample rules
  where they help, but do not overfit to text. Voice-reference quality is
  acoustic, so audition remains mandatory.
- Preserve raw transcript data and do not mutate Podlove, DOTe, WebVTT, or
  `Transcript.speakers` while deriving candidates.

The implementation should not pretend transcript labels prove identity. A
candidate is a timed passage for a label. It becomes a contributor voice
reference only after the editor maps or selects the contributor and confirms the
audio by listening.

## Reuse

Reuse these existing pieces rather than building a separate mini-application:

- Contributor voice-reference storage and validation from
  `ContributorVoiceReference.clean()`.
- Private/approved reference selection from
  `ContributorVoiceReferenceQuerySet.usable_known_speaker()`.
- Voxhelm payload assembly from `build_known_speaker_references()` and
  `build_known_speaker_reference_entry()`.
- Transcript label extraction from `Transcript.get_speaker_labels()`.
- Transcript sample text cleanup and timestamp parsing from
  `Transcript.get_speaker_samples()` and its helper methods.
- Episode contributor context from `get_speaker_mapping_context()`.
- Existing audio source discovery from `get_transcript_audio_sources()`.
- Existing admin audition mechanics in `cast/transcript/edit.html`:
  `data-cast-speaker-audio`, `data-cast-speaker-seek`, and shared audio playback.
- `SpeakerContributorMappingForm` choice construction as prior art for showing
  contributor assignments, while preserving contributor ids for the new create
  action.

## Open Questions / Risks

- Contributor resolution: should voice-reference candidates appear only after a
  speaker label has been mapped to an episode contributor, or should the
  candidate row include its own contributor chooser? Requiring mapping first is
  simpler, but the current mapping form cleans to display names, so the new
  create action still needs contributor ids.
- Audio reused by multiple episodes: when one `Transcript.audio` belongs to more
  than one episode, the UI needs an explicit source-episode choice or should omit
  `source_episode` rather than guessing.
- Detection quality: contiguous same-label transcript segments are only a proxy
  for clean solo speech. They can include cross-talk, music beds, applause,
  laughter, breath noise, edits, or diarization lag at turn boundaries.
- Length policy: the first implementation needs defaults for minimum, target, and
  maximum candidate length. The runbook's 8 second minimum and 30 second cap are
  a reasonable starting point, but should be validated against real podcast
  material.
- Multiple candidates: one top run may be bad despite its duration. The UI should
  probably show at least two or three candidates per contributor and avoid
  creating duplicates of an already approved equivalent range.
- No clean run: contributors with no long solo passage need a clear empty state
  and a path back to manual review or uploaded private clips, without making raw
  seconds entry the main workflow.
- Non-ASCII names: the UI should rely on contributor ids and database values, not
  shell-escaped display-name strings. Public speaker output still has exact-name
  constraints elsewhere, but voice-reference creation should not depend on a
  typed name matching byte-for-byte.
- Accessibility: audition controls need real buttons, keyboard support, clear
  labels that include contributor/range context, and a way to understand what is
  playing without relying only on visual timestamps.
- Playback boundaries: seeking is already implemented; stopping at the candidate
  end is new. The JavaScript must handle repeated clicks, pausing, manual seeks,
  and browsers that reject autoplay promises.
- Privacy: voice references remain private editorial data. The candidate picker
  can live in authenticated Wagtail admin, but it must not create public APIs,
  static exports, theme context, feed data, or committed artifacts containing
  reference ranges. Uploaded reference clips still need protected storage.
- Consent: the one-click creation path must not bypass
  `ContributorVoiceReference.clean()`. `APPROVED` must require explicit
  `consent_confirmed=True`, and lower-trust actions should create `PENDING`
  references instead.
- Tests and fixtures: candidate detection needs representative Podlove fixtures
  with start/end timings, adjacent labels, missing timings, short runs, and
  non-ASCII contributor display names.

## Done When

The eventual implementation slice is complete when:

- The transcript edit admin offers candidate source ranges derived from an
  existing diarized transcript, without requiring editors to type
  `start_seconds` or `end_seconds`.
- Candidates are grouped by speaker/contributor context and can be auditioned
  from the existing transcript audio player.
- The audition control plays the selected range, including a stop-at-end behavior
  or equivalent clear range boundary.
- Confirming a candidate creates a `ContributorVoiceReference` with
  `source_audio`, optional `source_episode`, and pre-filled range bounds.
- Approved creation is possible only after explicit consent confirmation; without
  consent, the flow blocks approval or creates a pending reference.
- Existing model invariants stay intact: private data only, clip-or-range
  exclusivity, source-range bounds, `start < end`, and no public exposure.
- The Contributor snippet still lets editors inspect and manage created
  references.
- Tests cover candidate derivation, admin create behavior, validation failures,
  duplicate/empty states, consent gating, and public-output non-exposure.
- Docs and release notes are updated when the feature ships, because the editor
  workflow changes.
