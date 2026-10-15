# Transcript glossary: correct names and technical terms after transcription

Status: 2026-10-15, proposed. Related to
[2026-05-18-speaker-diarization.md](2026-05-18-speaker-diarization.md) (same
sidecar and review pattern) and Voxhelm's
`specs/2026-10-15_parakeet_asr_backend.md` (the ASR that produces the text).

## Why

Speech recognition cannot spell names it has never seen, and no ASR setting
fixes that: Parakeet takes no prompt, and whisper.cpp's prompt was never sent
for batch jobs. A count on six Django Chat pilot episodes (55,202 words,
Parakeet TDT 0.6B v3 with the deployed settings, judged from text context
without listening, so approximate and recall-limited) found about 180 wrong
names and terms, roughly 3 per 1,000 words or 30 per episode:

| class | count | examples |
| --- | --- | --- |
| in the episode's contributors or show notes | 92 | "John" for Jon Gould (22x in episode 219), "Foxy Talent" (Foxley), "Scaff" (scaf, 10x), "debt 19" (DEP 19, 9x), "Button Down" (Buttondown), "Turnstyle", "EuroParton", "Hendricks Parker" |
| recurring ecosystem terms | 70 | "rough" (Ruff, 8x), "Gunacorn" (Gunicorn, 6x), "Ginger" (Jinja, 3x), "Janganaut", "JengaCon", "PySharm", "Roku" (Heroku), "DirInf" (direnv) |
| other people and places | 18 | "Simon Sherette" (Charette), "Hinnick" (Hynek), "Bukas Langa", "Charlie Marshall" (Marsh) |

The biggest single source is homophones of contributor names ("John"/"Jon"),
which only a glossary can fix. The recurring terms repeat across episodes,
so a per-show list pays off quickly. whisper.cpp is no better overall (it
spells Buttondown, Turnstile and Ryle right, DjangoCon and PyCon wrong).

A local LLM (Qwen3.6-27B 4-bit, 735 s for the six episodes) asked to flag
misrecognised names found many of these but also proposed wrong fixes
("Tim Schilling" -> "Tim Graham", "Calvin" -> "Carlton", "Django on the Med"
-> "Django on the main", "Le Monde Diplomatique" -> "London Review of Books")
and missed 12 of the 22 "John" and all four "Foxy". It is usable for
proposals an editor approves, not for unattended rewriting. An earlier pilot
that restricted the LLM to glossary targets and similar spellings kept 26
fixes on episode 219, 24 of them right.

## Goals

- Editors maintain the spellings once, in Wagtail, and every new or
  regenerated transcript of that show gets them.
- Unattended corrections are deterministic and introduce no wrong text on the
  pilot set; anything uncertain is a proposal an editor approves.
- Corrections reach all public formats (Podlove, DOTe, WebVTT) and survive a
  re-application from the raw Voxhelm text. Transcript text is not part of
  the site search today (`Transcript` indexes no text field); the corrected
  text shows up in the player's transcript search, and site search of
  transcripts stays out of scope.
- Voxhelm stays show-agnostic: it never stores a glossary.

Non-goals: general grammar or punctuation fixes, rewriting sentences,
correcting the audio-level ASR (no prompt or hotword support), translating.

## Where the glossary lives

Three sources, merged per episode at correction time. Only the third needs
manual upkeep.

1. **Contributors** (existing `Contributor` snippet). `display_name` is the
   canonical full spelling. New optional field `transcript_variants`, one
   `variant => replacement` pair per line, for example `John Gould => Jon
   Gould` and `John => Jon`; a line without `=>` means the replacement is
   `display_name`. An explicit replacement is needed because a first-name
   variant must not expand to the full name ("John's" -> "Jon's", not "Jon
   Gould's"). Variants of a contributor apply only in episodes that credit
   that contributor, so "John" -> "Jon" never fires in an episode without
   Jon.
2. **Episode** (derived, no new field in slice 1). Link texts of the
   episode's show notes (rich text in `body`) and "by <Author>" phrases, the
   same sources the pilot glossary came from. These are canonical spellings
   without variants, so they feed proposals only (see "Matching"), never
   unattended replacement.
3. **Show** (new snippet `TranscriptGlossaryTerm`, foreign key to `Podcast`,
   registered as a Wagtail snippet viewset filterable by podcast): `term`
   (canonical spelling), `variants` (one per line), `notes` (internal). A
   snippet, not an inline on the podcast page, so editing it needs no page
   publish and the transcript review can add entries directly. Per show
   because Django Chat and the German Python Podcast need different terms.
   Unique per podcast and case-insensitive `term`; a variant may belong to
   only one term of the same podcast (form validation).

Seeding: the first Django Chat list comes from the pilot count (about 40
entries: Ruff, Gunicorn, Jinja, DEP, Djangonaut Space, DjangoCon, PyCharm,
Heroku, DSF, PyLadies, Simon Charette, Hynek, Jacob Walls, Jeff Triplett,
Paul Everitt, Łukasz Langa, ...), loaded by a data-only management command,
not a migration.

## Matching

Input is the raw text of each transcript segment (see "Storage") and the
effective glossary of one episode: variants of the contributors it credits
plus its podcast's show terms. Variants are normalised (case-folded,
whitespace collapsed, typographic apostrophes folded) before use. If the same
normalised variant maps to different replacements in that effective glossary
(two credited contributors, or a contributor and a show term), it is not
applied automatically; its matches become proposals listing both targets.
Two kinds of results:

- **Automatic replacement**: a listed variant (contributor of this episode or
  show term) matches a whole-word, case-insensitive phrase in a segment. The
  match is replaced by the canonical spelling. Longer variants win over
  shorter overlapping ones ("John Gould" before "John"). Matches inside a
  longer token never count ("Johnson" is not "John"). Possessives keep their
  suffix ("John's" -> "Jon's").
- **Proposal**: everything that is not an exact listed variant. Sources:
  fuzzy matches of glossary terms against word n-grams (similarity >= 0.8
  on letters and digits, at least two words for multi-word terms, never a
  plain dictionary word alone) and, from slice 3 on, the LLM pass. Matches
  never span two segments. A
  proposal carries segment position, start ms, original text, replacement,
  source and score, and changes nothing until an editor approves it.

Variants are the editor's statement that a phrase is always wrong in this
show. Common words are therefore not allowed as show-term variants: the
form rejects a variant that is in the built-in common-word list for the
transcript language (for example "rough", "kind", "tilt", "copier"); such
errors are left to the LLM proposals of slice 3; until then they have no
proposal path, since fuzzy matching also skips single dictionary words.
Contributor first names ("John") are allowed because they are scoped to
episodes that credit the contributor. The common-word lists exist for
English and German, the two transcript languages in use; a transcript in
another language gets no automatic show-term replacement.

## Which episode supplies the context

An `Audio` can be used by several episodes, possibly of different podcasts,
but it has one `Transcript`, so corrections are global to that audio. The
episode whose contributors and podcast form the glossary is therefore stored
with the corrections (`episode_id` in the sidecar):

- At import it is the episode `resolve_audio_episode` returns. When that is
  ambiguous (it returns `None` for audio shared without explicit context),
  no automatic replacement runs; the review view asks the editor to pick one
  of the episodes using the audio, and that choice is stored.
- Re-application always uses the stored episode. If that episode no longer
  uses the audio, re-application stops and the review asks again.

## Storage and re-application

Like known-speaker suggestions, corrections live in a private sidecar next to
the public files and are applied by start time:

- New private `FileField` `Transcript.corrections` (same storage as
  `speakers`) holding JSON:
  `{"source_fingerprint", "episode_id", "glossary_fingerprint",
  "segments": [{"start_ms",
  "raw_text", "replacements": [{"start", "end", "from", "to", "source",
  "state"}]}], "proposals": [...]}`.
  `raw_text` is the Voxhelm text as imported; `state` is `auto`, `approved` or
  `rejected`. The sidecar is written at import, before anything is applied,
  so `raw_text` never contains corrections. For a transcript imported before
  this feature (no sidecar), the first run takes the current segment text as
  raw text; speaker application changes only speaker fields, so that text is
  still Voxhelm's.
- Applying is a pure function of raw text plus non-rejected replacements; it
  rewrites the segment text in Podlove, DOTe and WebVTT, matched by
  `start_ms` as `apply_known_speaker_suggestions` does, inside one
  `StagedFileReplacementGroup`. Running it twice gives the same files.
- Speaker mappings: today `TranscriptSpeakerMapping.source_artifact_fingerprint`
  must equal `transcript_artifact_fingerprint()`, a hash over the public file
  bytes, so any text correction would turn approved speaker mappings stale
  and hide their names. Slice 1 therefore adds `Transcript.source_fingerprint`,
  set whenever artifacts are imported from Voxhelm or uploaded in the admin
  (the hash of the artifacts as received), and switches the mapping checks
  (`sync_speaker_mappings`, the mapping form, transcript sanitisation) to it.
  Text corrections and speaker application leave it unchanged; a new import
  or upload changes it and invalidates mappings as before. Existing rows are
  migrated by setting `source_fingerprint` to the current
  `transcript_artifact_fingerprint()`.
- The sidecar's `source_fingerprint` is that same value. A regenerated
  transcript (new Voxhelm job or upload) gets a fresh sidecar;
  approved proposals are not carried over by position, but an editor who
  wants them permanent adds them as variants ("add to glossary" in the review).
- Corrections run automatically after a Voxhelm import completes and on an
  explicit "re-apply glossary" action (after glossary edits). Rejected
  automatic replacements stay rejected for that sidecar.
- Speaker suggestions and text corrections touch different fields of the same
  segments; both apply by `start_ms`, so their order does not matter. The
  implementation must keep one write path per format so the two never
  overwrite each other's changes.

## Review UI

On the transcript edit view next to the known-speaker review:

- Summary: automatic replacements and open proposals per term.
- A table of proposals with context (the sentence, with the span marked),
  "approve", "reject", "approve and add to glossary" (adds the original as a
  variant of the show term or contributor; refused for common words).
- Automatic replacements are listed too and can be rejected one by one.
- Optional audio play of the segment (the speaker review already plays
  samples).

## Voxhelm's part (slice 3)

The LLM needs the GPU workers, so it runs in Voxhelm as a text job, not
inside django-cast:

- New job type `transcript_terms` (lane `batch`, non-interactive admission on
  the worker). Input: segment texts with `start_ms`, language, glossary terms
  (canonical spellings only) and contributor names. No audio, no show id.
- The worker runs a pinned local model (candidate: `mlx-community/Qwen3.6-27B-4bit`,
  pinned by commit and sha256 like Parakeet, 15 GB of weights; measured
  134 s for the 56-minute episode 219 on atlas, 735 s for all six pilot
  episodes) and returns proposals only.
  Voxhelm filters them before returning: the original must occur in the
  segment, original and replacement must differ by more than case, and the
  replacement must either be a glossary or contributor spelling or reach
  similarity >= 0.6 with the original. It never returns rewritten text.
- django-cast submits the job after the import (if enabled in
  `VoxhelmSettings`), records the Voxhelm job id and the transcript's
  `source_fingerprint` in the sidecar, and imports the result as proposals
  with source `llm` only if both still match. A result that arrives after
  the transcript was regenerated or re-uploaded is discarded.
- Voxhelm keeps nothing about the glossary after the job; the job input is
  stored like other job inputs and expires with them.

Whether the model fits next to Parakeet and pyannote on `studio` and `atlas`
is measured before slice 3 starts; the Parakeet spec recorded 20.5 to 25.5 GB
for two consecutive 2:17 h jobs on atlas (64 GB).

## Slices

1. **Glossary and automatic replacement**: `transcript_variants` on
   `Contributor`, `TranscriptGlossaryTerm` snippet, corrections sidecar,
   apply/re-apply, seeding command, docs and release notes. No proposals yet.
2. **Proposals and review**: fuzzy proposals from contributors, show terms and
   show-note terms; review UI with approve/reject/add to glossary.
3. **LLM proposals via Voxhelm**: the `transcript_terms` job in Voxhelm
   (separate Voxhelm spec), submission and import in django-cast.

Each slice ships only if its measurement passes (next section).

## Verification

Gold: before slice 1 the tally above is frozen as an occurrence-level
dataset in the repository's test data: per occurrence the episode (feed guid
and title), the segment `start_ms` in the frozen raw pilot artifacts (the
Parakeet output used for the count, stored alongside), the original text,
the correct spelling and the class. Cases judged uncertain from text are
settled by listening before the freeze. Each slice is scored against that
file per occurrence: fixed, missed, or wrongly changed (any replacement not
in the gold, or with a different target). Gates:

- Slice 1 with the seeded Django Chat list and contributor variants: no
  introduced wrong text in the six episodes (every automatic replacement is
  right), and at least half of the 180 occurrences fixed.
- Slice 2: proposals cover at least 80 % of the remaining occurrences in the
  contributor/show-note class; precision of proposals is reported, not gated.
- Slice 3: LLM proposals add coverage on the recurring-term and other-people
  classes beyond slice 2; report precision and added coverage, and adopt it
  only if it finds at least 20 % of the occurrences the earlier slices miss
  at a precision of at least 70 %.
- Then on staging: re-apply on the pilot episodes, check that Podlove, DOTe
  and WebVTT show the same corrected text, that the player's transcript
  search finds "Jon Gould", and that approved speaker names are still shown.

## Risks

- A wrong variant corrupts every episode of the show. Mitigations: variants
  are explicit, common words are refused, contributor variants are scoped to
  credited episodes, every automatic replacement is listed and can be
  rejected, and raw text is kept for re-application.
- Homophones that are right elsewhere ("John" for another John in a Jon
  episode). Accepted for contributor variants; the review lists each
  replacement with context.
- Format drift: applying text by `start_ms` relies on the three formats
  sharing segment starts, as the speaker application already does.
- LLM memory and run time on the shared workers (slice 3, measured first).
