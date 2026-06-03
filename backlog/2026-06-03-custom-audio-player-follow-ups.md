# Custom Audio Player — Follow-ups (polish + caching)

## Status

Planned. Small follow-up backlog to the **implemented** custom audio player (see
`2026-06-02-custom-audio-player.md`, now marked implemented). These are UX nitpicks
and a caching decision surfaced while reviewing the player on
`python-podcast.staging.django-cast.com` and the django-chat dev server. Kept
separate so the main spec stays a record of what shipped.

Each item below is independently shippable; none is started yet.

## 1. Stable toggle-button width (no resize on open)

**Problem.** The Transcript / Chapters toggle pills show their item count (e.g.
`145 LINES`, `9`) only while open. Toggling therefore changes the button's width,
which looks jittery and shifts the adjacent button.

**Options.**
- **A (preferred): move the count into the opened panel header.** The collapsed
  pill shows only "Transcript" / "Chapters"; the count renders inside the panel
  (next to the in-panel heading) once open. Button width never changes.
- **B: reserve a fixed-width placeholder** for the count on the collapsed pill
  (render it hidden but space-occupying), so width is stable whether open or not.

**Decision:** A — the count belongs with the content, and it keeps the collapsed
row clean. (Implementation: in `transcript-element.ts` / `chapters-element.ts`
render the count element inside the body header instead of the toggle; drop the
`.cast-panel:not(.is-open) .cast-panel__count { display:none }` rule.)

**Acceptance:** the toggle pills keep a constant width across open/close; a vitest
assertion that the count is not inside `.cast-panel__toggle`.

## 2. Transcript always starts folded

**Problem.** The transcript open/closed state persists in `localStorage`
(`cast-transcript-open`), so revisiting an episode can render the transcript
already expanded — which looks odd, and (with lazy loading) triggers a fetch on
load. Same for chapters (`cast-chapters-open`).

**Decision:** the panels always start **collapsed** on page load; the reader
clicks to open. Drop the persisted open-state restore (keep persisting the
`follow` / `tabbable` prefs, which are fine to remember). This also removes the
on-connect fetch for a "persisted-open" transcript (it now only fetches on an
explicit open), which interacts well with item 3.

**Acceptance:** loading an episode never shows an expanded transcript/chapters
panel and issues no transcript fetch until the user opens it; a vitest assertion
that a fresh mount is collapsed regardless of stored open-state.

## 3. Cache the transcript so re-navigation doesn't refetch

**Problem.** Navigating away and back to an episode, then opening the transcript,
refetches the full cues JSON from `cast:api:audio_player_transcript` every time.
Wasteful for large transcripts (2640 cues on python-podcast).

**Options (request: pick one or a combination):**

- **Option 1 — HTTP caching on the endpoint (recommended first step).** Add
  `Cache-Control: public, max-age=<e.g. 86400>, stale-while-revalidate=…` plus an
  `ETag` (derived from the transcript file fingerprint — we already track an
  S3/file fingerprint, see `2026-06-01-transcript-speaker-mapping-s3-fingerprint.md`)
  and honor `If-None-Match` → `304`. The player's `fetch()` then serves the cues
  from the browser HTTP cache on re-navigation with no app work (or a cheap 304).
  - *Pros:* tiny change, standard, no server state, fixes the user-visible reload,
    correct invalidation via ETag. The content is already public.
  - *Cons:* first load per browser still fetches; relies on browser cache policy.

- **Option 2 — server-side cache of the sanitized cues.** Cache the built +
  sanitized `{cues}` in Django's cache keyed by `(audio.pk, post.pk,
  sanitization-version, transcript-fingerprint)`, so repeat endpoint hits skip the
  file read + speaker sanitization.
  - *Pros:* cuts server CPU (sanitization runs once per version), shared across
    users; complements Option 1 for cache misses / first loads.
  - *Cons:* still a network round-trip unless combined with Option 1; needs
    invalidation on transcript/contributor change (the fingerprint in the key
    handles transcript edits; contributor/role changes need a version bump).

- **Option 3 — client storage cache (`sessionStorage`).** The player stores fetched
  cues keyed by `audioId`; on open it reads from storage and skips the fetch.
  - *Pros:* zero network on repeat within a session; survives navigation.
  - *Cons:* duplicates Option 1's benefit; storage-quota risk for very large
    transcripts; manual invalidation; extra JS. Lower priority once Option 1 lands.

- **Option 4 — persistent player (the planned `hx-boost` follow-up).** Keeping the
  JS context alive across navigation means the controller (and its cues) survive,
  so the transcript is never re-fetched or re-rendered and playback continues.
  - *Pros:* best UX. *Cons:* the large architectural follow-up (already recorded in
    the main spec's "Persistent Player" section).

**Recommendation:** **Option 1 now** (HTTP `Cache-Control` + `ETag`), optionally
**Option 2** to cut CPU. Defer 3/4. Acceptance: a second open of the same
transcript after navigation issues no new network request (served from cache) or a
`304`; a pytest asserting the endpoint sets `Cache-Control`/`ETag` and returns
`304` on a matching `If-None-Match`.

## 4. A django-chat episode with diarized speakers (verification)

**Problem.** The django-chat dev DB has no episode with diarized (per-cue speaker)
transcript data, so the speaker-label layout (speaker as a block heading with the
cue text indented) couldn't be verified there. Episodes without speakers, and
without transcripts, both look correct.

**Options.**
- Copy an episode that has a diarized transcript from the python-podcast staging
  system into the django-chat dev DB (audio + `Transcript.podlove` with per-cue
  `speaker`/`voice` + the matching public contributors), or
- create a small synthetic django-chat dev episode with a hand-authored diarized
  transcript fixture.

**Acceptance:** opening that episode's transcript on the django-chat dev server
shows speaker headings with indented cue text (matching the python-podcast layout),
confirming the speaker rendering on django-chat. This is a **dev-data / manual
verification** task, not a code change.

## Out of scope

The persistent cross-navigation player (Option 4 above) remains the separate, larger
follow-up described in the main spec; it is not part of this note.
