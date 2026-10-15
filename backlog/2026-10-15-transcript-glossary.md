# Transcript glossary: correct names and technical terms after transcription

Status: 2026-10-15, proposed; slice 1 implemented on `develop` 2026-10-16,
staging verification and slice 2 open. Related to
[2026-05-18-speaker-diarization.md](2026-05-18-speaker-diarization.md) (same
sidecar and review pattern) and Voxhelm's
`specs/2026-10-15_parakeet_asr_backend.md` (the ASR that produces the text).

## Why

Speech recognition cannot spell names it has never seen, and no ASR setting
fixes that: Parakeet takes no prompt, and whisper.cpp's prompt was never sent
for batch jobs. A pilot on one show (six Django Chat episodes, 55,202 words,
Parakeet TDT 0.6B v3 with the deployed settings) found 179 wrong names and
terms, about 3 per 1,000 words or 30 per episode. Candidates came from a
fuzzy match against the show notes and from a local LLM; each was judged in
context, and the 34 that context could not settle were listened to (8 kept
as errors, 17 were no error, 9 stayed unclear and were dropped). The count is
recall-limited: errors neither method flagged are missing.

| class | count | examples |
| --- | --- | --- |
| in the episode's contributors or show notes | 92 | "John" for Jon Gould (22x in one episode), "Scaff" (scaf, 14x), "debt 19" (DEP 19), "Button Down" (Buttondown), "Turnstyle", "EuroParton", "Hendricks Parker" |
| ecosystem terms | 71 | "rough" (Ruff, 8x), "Gunacorn"/"GunnarCorn" (Gunicorn), "Ginger" (Jinja), "Janganaut", "JengaCon", "PySharm", "Roku" (Heroku), "DirInf" (direnv) |
| other people and places | 16 | "Simon Sherette" (Charette), "Hinnick" (Hynek), "Bukas Langa", "Charlie Marshall" (Marsh), "Crack" (Kraków) |

How the errors repeat decides where a fix pays off:

| occurrence | count |
| --- | --- |
| a variant of a credited contributor's name | 26 |
| otherwise: the same misspelling recurs in another episode | 12 |
| otherwise: the correct term recurs in another episode, misheard differently | 18 |
| otherwise: the correct term occurs in only this episode | 123 |

(Rows are checked in this order; misspellings compared case-insensitively.)

So a show-wide list of known misspellings would have fixed about 12 of 179
in an episode it was not built from, 38 with the contributor variants. The
lever is inside one transcript: the same error repeats ("Scaff" 14x, "John"
22x), so the 179 occurrences need only 95 decisions when one decision per
correct spelling applies to the whole transcript (121 if every distinct
misspelling needed its own decision). The correct spellings are mostly
already in the episode's show notes and contributor names.

whisper.cpp is no better overall (it spells Buttondown, Turnstile and Ryle
right, DjangoCon and PyCon wrong). A local LLM (Qwen3.6-27B 4-bit, 735 s for
the six episodes) asked to flag misrecognised names found many errors but
also proposed wrong fixes ("Tim Schilling" -> "Tim Graham", "Calvin" ->
"Carlton", "Django on the Med" -> "Django on the main", "Le Monde
Diplomatique" -> "London Review of Books") and missed 12 of the 22 "John" and
all four "Foxy". It is usable for proposals an editor approves, not for
unattended rewriting.

The pilot data belongs to the show, not to django-cast: the occurrence-level
gold lives in the Django Chat site project (`django-chat`,
`data/transcript-glossary/`), with each occurrence's own transcript segment
only (sentence-level segments of at most 30 s; none of the 179 holds more
than one sentence); the full raw transcripts are kept private and are not
committed anywhere.

## Goals

- Editors fix a misheard term once per transcript: one decision per correct
  spelling applies to every occurrence proposed for it in that transcript,
  whatever the misspellings.
- Correct spellings come mostly from data the episode already has (show-note
  link texts, contributor names), so the common case needs no list upkeep.
- A per-show glossary in Wagtail holds recurring terms and grows from review
  decisions ("add to glossary"), not from a seeding effort.
- Unattended corrections are deterministic and introduce no wrong text;
  anything uncertain is a proposal an editor approves.
- Corrections reach all public formats (Podlove, DOTe, WebVTT) and survive a
  re-application from the raw Voxhelm text. Transcript text is not part of
  the site search today (`Transcript` indexes no text field); the corrected
  text shows up in the player's transcript search, and site search of
  transcripts stays out of scope.
- Voxhelm stays show-agnostic: it never stores a glossary.

Non-goals: general grammar or punctuation fixes, rewriting sentences,
correcting the audio-level ASR (no prompt or hotword support), translating.

## Where the glossary lives

Three sources, merged per episode at correction time:

1. **Contributors** (existing `Contributor` snippet). `display_name` is the
   canonical full spelling. New optional field `transcript_variants`, one
   `variant => replacement` pair per line, for example `John Gould => Jon
   Gould` and `John => Jon`; a line without `=>` means the replacement is
   `display_name`. An explicit replacement is needed because a first-name
   variant must not expand to the full name ("John's" -> "Jon's", not "Jon
   Gould's"). Variants of a contributor apply only in episodes that credit
   that contributor, so "John" -> "Jon" never fires in an episode without
   Jon. Without variants, the contributor's name parts are still proposal
   targets.
2. **Episode** (derived, no new field). Link texts of the episode's show
   notes (rich text in `body`) and "by <Author>" phrases, the same sources the
   pilot used. These are canonical spellings without variants, so they feed
   proposals only (see "Matching"), never unattended replacement. Derived
   from them (`episode_terms` in `cast.transcripts.glossary`):
   - **Full spellings, listed first:** link texts with bracket notes removed
     (the notes' parts are kept) and a leading article dropped ("The
     Go-Giver" -> "Go-Giver"), title parts split on ":" or " - ", and
     "by <Author>" names, several joined by "and".
   - **Derived forms:** a trailing year or number after a name ("DjangoCon
     Europe 2027" -> "DjangoCon Europe"), CamelCase, acronym and hyphenated
     tokens of a link text ("EuroPython", "DEPs"), author surnames, and an
     "owner/repo" link text split into the repo and the CamelCase-split owner
     ("FarhanAliRaza/prongs" -> "prongs", "Farhan Ali Raza").
   - **URL host:** a link text that is a URL yields its host
     ("sixfeetup.com").
   - **Product prefix:** a lowercase repo, owner, host label or one-word link
     text that starts with "get", "use" or "try" also yields the rest when
     it has at least four letters ("getscaf" -> "scaf").

   Handles ("@show") are skipped. Terms with the same letters are kept once,
   full spellings before derived forms, so "SixFeetUp" and "Six Feet Up"
   form one group.
3. **Show** (new snippet `TranscriptGlossaryTerm`, foreign key to `Podcast`,
   registered as a Wagtail snippet viewset filterable by podcast): `term`
   (canonical spelling), `variants` (one per line), `notes` (internal). A
   snippet, not an inline on the podcast page, so editing it needs no page
   publish and the transcript review can add entries directly. Per show
   because shows differ (an English Django show, a German Python show).
   Unique per podcast and case-insensitive `term`; a variant may belong to
   only one term of the same podcast (form validation). Terms without
   variants are proposal targets; variants enable unattended replacement.

The show list starts empty and grows from the review ("add to glossary").
A site that already has a list can load it with a management command that
reads a JSON file (`term`, `variants`, `notes` per entry) for one podcast;
the data stays in the site project.

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
  plain dictionary word alone) and, from slice 2 on, the LLM pass. Matches
  never span two segments. Targets are the contributors' display names and
  their name parts, show terms and episode terms. Also never proposed:
  - a phrase that already spells the target;
  - a part of the target ("Django" for DjangoCon);
  - a lowercase identifier read aloud ("spec kit" for spec-kit);
  - a word split into a piece of fewer than three letters;
  - a different number ("DEP 10" for DEP 19).

  On overlap, the match with more matching letters wins. A
  proposal carries segment position, start ms, original text, replacement,
  source and score, and changes nothing until an editor approves it.
- **Decisions apply transcript-wide**: proposals with the same replacement
  (correct spelling) are grouped, whatever their originals ("Gunacorn",
  "Gunna Corn" -> "Gunicorn"), and the review decides the group once
  (approve, reject, or open it to decide originals or occurrences one by
  one). Each approved original becomes a transcript-scoped variant, so later
  re-applications and newly found occurrences of that misspelling in the
  same transcript are replaced without asking again.

Variants are the editor's statement that a phrase is always wrong in this
show. Common words are therefore not allowed as show-term variants: the
form rejects a variant that is in the built-in common-word list for the
transcript language (for example "rough", "kind", "tilt", "copier"); such
errors are left to the LLM proposals of slice 2; until then they have no
proposal path, since fuzzy matching also skips single dictionary words. A
transcript-scoped variant from an approved group may be a common word (the
editor saw the context, as with "rough" -> "Ruff" in a tooling discussion).
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
  "state"}]}], "proposals": [...], "decisions": [{"original", "to",
  "state"}]}`.
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
  approved proposals and decisions are not carried over, but an editor who
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

- Summary: automatic replacements and open proposal groups per term, and
  how many decisions are left.
- One row per proposal group (same replacement) with its originals, their
  counts and the first sentences as context (span marked), and "approve all",
  "reject all", "decide one by one", "approve and add to glossary" (adds the
  original as a variant of the show term or contributor; refused for common
  words).
- Automatic replacements are listed too and can be rejected one by one.
- Optional audio play of the segment (the speaker review already plays
  samples).

## Voxhelm's part (slice 2)

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
is measured before slice 2 starts; the Parakeet spec recorded 20.5 to 25.5 GB
for two consecutive 2:17 h jobs on atlas (64 GB).

## Slices

1. **Proposals from the episode and transcript-wide decisions**:
   `transcript_variants` on `Contributor`, `TranscriptGlossaryTerm` snippet
   and its import command, corrections sidecar with `source_fingerprint`,
   fuzzy proposals from contributors, show notes and show terms, grouped
   review with approve/reject/add to glossary, unattended replacement of
   listed variants, apply/re-apply, docs and release notes.
2. **LLM proposals via Voxhelm**: the `transcript_terms` job in Voxhelm
   (separate Voxhelm spec), submission and import in django-cast as further
   proposal groups.

Each slice ships only if its measurement passes (next section).

## Verification

Gold: the pilot's 179 occurrences, frozen before slice 1 in the show's site
project (for Django Chat: `django-chat`, `data/transcript-glossary/`). Per
occurrence: the episode (feed guid and title), the segment `start_ms` in the
raw pilot transcripts, the segment text (identical to the raw segment, one
sentence), the span as character offsets into that text, the original, the
correct spelling, the class and whether context or listening settled it. The raw
pilot transcripts are kept privately next to it and are not committed. Each
slice is scored per occurrence (fixed, missed, or wrongly changed: any
replacement not in the gold or with a different target) and per decision
(how many groups, keyed by episode and correct spelling, an editor has to
decide; 95 in the gold). Gates:

- Slice 1, run with an empty show list plus contributor variants for the
  credited guests: no wrong unattended replacement; proposals cover at least
  70 % of the 92 contributor and show-note occurrences; the editor needs at
  most one decision per (episode, correct spelling) for them. Proposal
  precision is reported, not gated.
- Slice 1, show list: measured leave-one-episode-out (a list built from the
  other five episodes' decisions), so its effect is not inflated by building
  and scoring on the same episode.
- Slice 2: LLM proposals are adopted only if they find at least 20 % of the
  occurrences slice 1 misses, at a precision of at least 70 %.
- Then on staging: re-apply on the pilot episodes, check that Podlove, DOTe
  and WebVTT show the same corrected text, that the player's transcript
  search finds "Jon Gould", and that approved speaker names are still shown.

### Slice 1 measurement (matching engine, 2026-10-15)

Measured on the six pilot episodes with an empty show list. Contributors are
the two hosts plus the guest named in the title, with variants only for the
credited guests. Results for the 92 contributor and show-note occurrences:

- **Coverage:** 72 (78 %); 26 fixed automatically and 46 proposed.
- **Without the product-prefix rule:** 58 (63 %), short of the gate.
- **The rule's gain flatters:** all 14 extra occurrences are one term, "scaf"
  from the link text "getscaf", in a single episode. Without that term,
  slice 1 would miss the gate.
- **Wrong automatic replacements:** none.
- **Decisions:** exactly one group per (episode, correct spelling); 19 keys.
- **Proposals:** 89 in 39 groups. 46 match a gold occurrence, a precision of
  52 %. Many of the others look like real errors the gold does not list
  ("button down", "Django in the med").
- **Run time:** about 5 s for all six episodes.
- **Gaps:** the misses are terms the notes do not spell as spoken ("DEP 20",
  "DEPs" for "dips"/"depths", "technical governance", a misspelt author
  name), or originals below 0.8 similarity ("six speed up", "EuroPi",
  "Herbert Woolworths").
- **Ecosystem and other names:** none covered (K 0/71, O 0/16). That is
  expected, since those terms are not in the show notes.

Leave-one-episode-out show list (term = correct spelling; variants are the
other five episodes' originals, common words excluded):

- **Coverage:** 72 of the 92 contributor and show-note occurrences (30
  automatic, 42 proposed), 9 of 71 ecosystem terms proposed, and 30 of 179
  occurrences fixed automatically overall. Only "Six Feed Up" recurs as a
  non-common misspelling; the recurring "rough" (Ruff) is refused as a
  common word.
- **Automatic replacements not in the gold:** 6. Four look correct: "Jango"
  or "Jang" -> Django three times, and "learnjango.com" -> learndjango.com.
  Two are questionable: "Jang" -> Django where "jang" was a false start
  (once before another word, once directly before "Django"). Both come
  from the variant "Jang" learned in another episode, and the review lists
  them so they can be rejected.

## Risks

- A wrong variant corrupts every episode of the show. Mitigations: variants
  are explicit, common words are refused for show terms, contributor
  variants are scoped to credited episodes, transcript-scoped decisions stay
  in their transcript, every automatic replacement is listed and can be
  rejected, and raw text is kept for re-application.
- "Approve all" on a group can hide a single wrong occurrence (a real
  "John" among 22 for Jon). The group shows every sentence on request, and
  each replacement can be rejected afterwards.
- Homophones that are right elsewhere ("John" for another John in a Jon
  episode). Accepted for contributor variants; the review lists each
  replacement with context.
- Format drift: applying text by `start_ms` relies on the three formats
  sharing segment starts, as the speaker application already does.
- LLM memory and run time on the shared workers (slice 2, measured first).
