# Custom Audio Player Web Component (Transport + Transcript + Chapters)

## Status

**Implemented.** This note is the record of what shipped. The custom player
replaces Podlove on the episode detail path behind `CAST_AUDIO_PLAYER="custom"`
and is merged to django-cast `develop` (through `e23a2887`): lazy transcript
loading, the transport/transcript/chapters redesign (thin bar, elapsed+remaining,
compact toggle row with single-open accordion, speaker layout), the public
transcript endpoint, settings/checks, docs, and tests (124 vitest cases; backend
at 100% coverage). It is deployed to `python-podcast.staging.django-cast.com`
(production stays on Podlove) — Playwright-verified, axe-clean — and adopted on the
django-chat dev server (forest-green, Podlove-styled; `feat/custom-player`).
cast-bootstrap5 wiring + a11y fixes live on its `feat/custom-player-rev4` branch.

Further polish and a transcript-caching decision are tracked separately in
**`2026-06-03-custom-audio-player-follow-ups.md`** (stable toggle width, always-
folded-on-load, transcript caching options, a diarized-speaker verification
episode for django-chat) so this note stays a record of the as-built design rather
than growing. The remaining large item — a persistent cross-navigation player — is
in the "Persistent Player" section below.

The design history that produced the implementation follows (revisions 1–4).
Revision 4 (this document) was implemented as described, with two as-built
deltas worth noting: the collapsed panel bodies are hidden via `display:none`
(a Blink `grid-rows:0fr` collapse leaked ~1 line with an auto-overflow scroll
child), and the two toggle buttons are kept in a stable row via `display:contents`
flattening with the opened body dropping full-width beneath them.

This revision (**revision 4**) folds in what we learned from running the player
on real episodes plus a second round of UX, performance, and cross-repo
requirements. The substantive changes from revision 3 are:

1. **Lazy-load the transcript on demand.** The transcript is no longer inlined
   into the detail-page HTML for any episode size. Detail pages ship only player
   metadata + chapters (small); transcript cues are fetched once, from the
   existing endpoint, the first time the user opens the Transcript panel. This
   removes the per-request transcript build/sanitization from every episode page
   render and removes `CAST_PLAYER_INLINE_TRANSCRIPT_MAX_BYTES` and its inline
   path entirely.
2. **Transport + transcript UI redesign.** Thinner progress bar; an
   elapsed-time / remaining-time readout (Podlove-style `-mm:ss`); compact
   collapsible **buttons** for Transcript and Chapters (no full-width panels, no
   cut-off preview text when collapsed); the Chapters button appears only when
   chapters exist; speaker labels rendered as their own line with the cue text
   indented beneath; keyboard-shortcuts help and the keyboard-navigable-cues
   toggle restyled to match the player's other controls instead of raw native
   `<details>`/checkbox widgets.
3. **python-podcast staging rollout (Phase B).** Configure the staging site
   (`python-podcast.staging.django-cast.com`) to use the custom player while
   production keeps Podlove, so external Lighthouse can be run against the custom
   player in a real browser on a real site.
4. **django-chat adoption (Phase C).** Bring the custom player to django-chat,
   styled to match its existing forest-green Podlove look, wire its share dialog
   to the player's read-only position API (the player already supports
   share-with-current-time and `?t=` receiver-side seek — capabilities Podlove's
   iframe blocked), and drive the chapters button from chapter data so it is
   hidden when an episode has none. Stage it first; do not replace production
   Podlove yet.

Review history:

- Round 1 (`pi`): NEEDS REVISION — addressed in revision 2.
- Round 2 (`pi` + an independent reviewer): NEEDS REVISION — addressed in
  revision 3.
- Round 3 (`pi`, this revision-4 review circle): round 3a NEEDS REVISION (lazy-
  transcript failure state, ready-wiring race, django-chat template branching,
  stale token list, controls-row ownership, endpoint `post_id` scope, KPI LOC) →
  fixed; round 3b NEEDS REVISION (fetch-once vs retry wording, Phase C tag
  variables, Phase C token example) → fixed; **round 3c: CLEAN.**
- Round 4 (independent reviewer, Codex / GPT-5): **CLEAN** — 0 critical, 0
  warning, 1 suggestion (backend-KPI wording: "55 pytest test functions / 83
  collected with parametrization") applied; all eight prior findings confirmed
  resolved; cycle closed.

## Implementation Status and KPIs (measured 2026-06-03)

Baseline numbers for the shipped player, to track against the redesign and the
Lighthouse goal. (Built assets under `src/cast/static/cast/vite/`; LOC excludes
the legacy `podlove-player.ts`.)

| KPI | Value |
| --- | --- |
| Custom-player JS bundle | 26,995 bytes raw / **7,641 bytes gzip** |
| Custom-player CSS bundle | 11,233 bytes raw / **2,578 bytes gzip** |
| Combined shipped bytes | ~38 KB raw / **~10.2 KB gzip** |
| Podlove embed for comparison | ~138 KB Vue app in an iframe |
| Frontend source LOC (9 TS files) | ~1,585 |
| Frontend test LOC / cases | ~960 LOC / **58 vitest cases** (5 audio test files) |
| Backend source LOC | 381 (`player.py` 345 + `cast_audio_player.py` 36) |
| Backend test LOC / cases | 529 LOC / **55 pytest test functions** (83 collected with parametrization; `player_test.py` + `custom_player_template_test.py`) |
| Test coverage | **100%** (repo enforces `fail_under = 100`) |
| Lighthouse (perf/a11y) | **Not yet measured** — unblocked by the Phase B staging deploy (external run in a real browser) |

These belong in the docs/release notes as the "why a custom player" evidence:
~10 KB gzip with no iframe and no framework baseline, versus the ~138 KB Podlove
embed.

KPI acceptance for revision 4: combined shipped bytes stay ≤ ~12 KB gzip after
the redesign; detail-page HTML no longer carries transcript cues; Lighthouse
performance and accessibility scores are recorded from the staging run (target:
no accessibility audit failures; performance not regressed by the player).

## Background: the current integration

The current player is the Podlove Web Player v5, integrated as:

- `javascript/src/audio/podlove-player.ts` — a vanilla `HTMLElement` wrapper that
  lazy-loads Podlove's `embed.5.js` via a facade (IntersectionObserver) or a
  click-to-load button.
- `src/cast/templates/cast/audio/audio.html` — renders `<podlove-player>` or, when
  `CAST_AUDIO_PLAYER == "custom"`, the custom player include. The template is
  selected by `AudioChooserBlock.get_template` (`src/cast/blocks.py`), so themes can
  override it by `template_base_dir`.
- On **server-rendered** themes (plain, bootstrap5, python-podcast, django-chat),
  the player is rendered by the StreamField `audio` block via `audio.html` —
  `post_body.html` iterates `page.body` and calls `{% include_block block %}`. The
  detail context exposes `has_audio` (`src/cast/models/pages.py`); list/index
  contexts expose `use_audio_player` (`src/cast/models/repository/contexts.py`).
- API: `src/cast/api/serializers.py` (`AudioPodloveSerializer`) returns an inline
  Podlove `transcripts` field and applies public speaker sanitization
  (`src/cast/transcript_sanitization.py`). The custom player does **not** reuse this
  Podlove-shaped payload.
- `src/cast/podlove.py` builds the Podlove theme/config JSON.

Note: stored transcript data is **raw**. `Transcript.podlove_data`
(`src/cast/models/transcript.py`) reads the stored file directly with no
sanitization; sanitization happens only on public output. The custom payload
builder therefore runs transcript data through the public sanitization path
(`src/cast/player.py:_load_sanitized_segments`), never reading `podlove_data`/
`transcript.podlove.url` directly for public output.

Project conventions: this repo uses `AGENTS.md` (there is no `CLAUDE.md`); docs
and release notes must be updated in the same change when user-facing behavior
changes; `just check` (lint + mypy + pytest at 100% coverage) must pass.

## Summary

A custom, self-rendering audio player built as **vanilla TypeScript Web
Components** (no runtime dependencies) replaces Podlove on the episode detail
page. The player gets its **metadata and chapters inlined into the page as JSON**
(`json_script`); the **transcript is fetched on demand** from a dedicated
endpoint the first time the user opens the Transcript panel. The player renders
immediately, looks plain, adapts to the host site's colors via CSS custom
properties (light and dark), and is engineered for top Lighthouse performance and
accessibility scores. There is no hover/click-to-load facade.

A single **audio controller** (one `<audio>` element plus playback state) is the
single source of truth. Three views are bidirectionally coupled to it:

1. **Transport UI** — play/pause, draggable/seekable progress bar (thin),
   elapsed + remaining time, a share button, and a keyboard-shortcuts affordance.
   No volume control, no playback-speed control.
2. **Transcript** — speaker identification, in-transcript search, current-cue
   highlight, follow-along auto-scroll, click-a-cue-to-seek, and
   drag-the-bar-jumps-the-transcript. Collapsed by default; its cues load lazily.
   Placeable anywhere on the detail page.
3. **Chapters** — show the current chapter during playback and seek when a
   different chapter is selected. The chapters affordance is shown only when
   chapter data exists.

Everything else — show notes / info, download, embed — remains an independent
page concern. The one allowed cross-boundary relationship is one-directional:
external share UI may **read** the player's current position through a small
public API, and the player honours a `?t=<seconds>` deep link on load. The player
never depends on share, download, or info.

The player is built **dual-mode**: it works standalone today (on the episode
detail page), and the same audio controller is designed to be promotable later to
a single **persistent player** that keeps playing across page navigation. That
persistence layer is a deliberate follow-up and is **not** part of this spec; the
next staging proof is tracked in
`2026-06-08-persistent-player-staging.md`.

## Problem

The Podlove Web Player is a ~138 KB Vue app rendered inside an iframe, causing:

- **Styling ceiling.** Podlove bakes styling into inline `style` attributes set by
  Vue at runtime and does not emit CSS custom properties; DOMPurify strips injected
  `<style>`. Prior restyling research (2026-05-17) recorded three failed attempts to
  match the player to site branding from outside the iframe — even fixing
  text/background contrast is effectively impossible.
- **Load cost and the facade.** Because the player is heavy, integrations gate it
  behind a hover/click facade (`podlove_load_mode`). That is exactly the
  "tab/hover to load" behavior we want to remove.
- **Runtime data fetch.** The player fetches episode JSON, transcript segments, and
  config at runtime, adding requests and latency.
- **Many players per page.** Overview/list pages render multiple players, which
  multiplies cost.

The backend already produces the underlying data (`Transcript`, `Audio`,
`ChapterMark`, `AudioPodloveSerializer`). So the work is a frontend replacement
plus a data-transport change (a dedicated, sanitized, normalized payload — small
inline metadata/chapters plus an on-demand transcript fetch — instead of a runtime
Podlove fetch). The data **model** is reused; the Podlove-shaped API payload is
**not**.

## Architecture

### Audio controller (single source of truth)

A framework-free `AudioController` (`javascript/src/audio/audio-controller.ts`)
owns one `HTMLAudioElement` and the playback state. It **extends `EventTarget`**
(platform-native pub/sub) — no custom reactive store, to keep shipped JS minimal.
The same pub/sub is reused unchanged by the future persistent player. The
controller never touches the DOM and never performs network I/O (so it stays
unit-testable); fetching is owned by `<cast-audio-player>`.

TypeScript surface (normative shape; names may be refined in code review):

```ts
type Cue = { start: number; end: number; speaker: string; text: string };
type Chapter = { start: number; title: string };
type Transcript = { cues: Cue[] } | { url: string } | null;
type PlayerPayload = {
  audioId: number;
  title: string;
  subtitle: string;
  duration: number | null;      // seconds; null if unknown until metadata loads
  poster: string;               // "" if none
  sources: { type: string; src: string }[];
  chapters: Chapter[];
  transcript: Transcript;       // {url} when a transcript exists; null when none.
                                // {cues} is only ever produced by the endpoint,
                                // never inlined into the page.
};

class AudioController extends EventTarget {
  constructor(audio: HTMLAudioElement, payload: PlayerPayload);

  get currentTime(): number;            // seconds
  get duration(): number | null;        // payload.duration ?? audio.duration (if finite)
  get paused(): boolean;
  get currentChapterIndex(): number;    // -1 if none
  get currentCueIndex(): number;        // -1 if none / not loaded

  // transcript state (revision 4)
  get hasTranscript(): boolean;         // payload.transcript carries a url or cues
  get transcriptLoaded(): boolean;      // setCues() has run with the real cues
  get transcriptLoading(): boolean;     // requestTranscript() fired, awaiting setCues()
  getCues(): readonly Cue[];

  play(): Promise<void>;                // swallows AbortError; emits "error" on real failure
  pause(): void;
  toggle(): void;
  seek(seconds: number): void;          // clamped to [0, duration ?? audio.duration ?? seconds]
  seekToCue(index: number): void;       // seek(cue.start + 0.01)
  seekToChapter(index: number): void;

  requestTranscript(): void;            // idempotent: if hasTranscript and not already
                                        // loaded/loading and a url is known, set loading
                                        // and emit "transcriptrequested" {url}. No fetch here.
                                        // While loading or after loaded it is a no-op.
  setCues(cues: Cue[]): void;           // installs cues, sets transcriptLoaded, clears
                                        // loading, recomputes currentCueIndex, emits
                                        // "cueschange" then "cuechange" if index changed
  transcriptFailed(): void;             // player calls this on fetch/parse failure: clears
                                        // transcriptLoading WITHOUT setting transcriptLoaded
                                        // (so a later requestTranscript() may retry) and
                                        // emits "transcripterror". No cues installed.

  destroy(): void;                      // removes audio listeners, pauses, clears state
}
```

Events (`CustomEvent` on the controller; `detail` noted): `play`, `pause`;
`timeupdate` `{currentTime, duration}` **coalesced to one dispatch per animation
frame**; `durationchange` `{duration}`; `seeking`/`seeked` `{currentTime}`;
`chapterchange` `{index}`; `cuechange` `{index}`; `cueschange` `{count}`;
`transcriptrequested` `{url}` (revision 4: emitted by `requestTranscript()` so the
player can fetch); `transcripterror` `{}` (revision 4: emitted by
`transcriptFailed()` so the view can drop its loading state); `error` `{error}`
(real load/playback failure, not play-interrupt).

Boundary/normalization rules (the controller assumes the builder delivers cues
sorted by `start`; it does not re-sort):

- A cue is current when `cue.start <= t < cue.end` (inclusive start, **exclusive
  end**). At exactly `t == cue.end`, that cue is not current.
- Gaps: if no cue satisfies the rule, `currentCueIndex = -1`.
- Overlaps: if multiple cues satisfy the rule, the **last** such cue wins.
- Chapters: a chapter is current when `chapter.start <= t < next.start`; the last
  chapter extends to the end. Before the first chapter's start → `-1`.
- Ended (`t >= duration`, and on the `ended` media event): an **explicit
  exception** — keep the last cue and last chapter highlighted so the
  transcript/chapter does not blank out at the very end. Empty cues/chapters → `-1`.
- Duration source: `payload.duration` if non-null; else `audio.duration` once it
  is finite (after `durationchange`); else `null`.
- Malformed cues never reach the controller — the backend builder skips them; the
  controller treats its input as already-normalized.

### Web components (views)

Custom elements extending `HTMLElement`, `cast-` prefixed, in
`javascript/src/audio/`. **Light DOM** (no Shadow DOM) so host CSS custom
properties cascade in and Lighthouse can audit the controls.

- `<cast-audio-player id="cast-player-{pk}" data-payload="cast-player-data-{pk}">` —
  reads the inlined JSON by `data-payload` id, builds the `<audio>` element and the
  `AudioController`, registers it, renders the transport UI, exposes the read-only
  public API, honours `?t=`, and (revision 4) **owns the on-demand transcript
  fetch**: it subscribes to `transcriptrequested` and fetches the url, keeping at
  most **one fetch in flight** and **never refetching after a successful load**
  (`transcriptLoaded` guards that). It calls `controller.setCues(cues)` on success
  or `controller.transcriptFailed()` on a non-OK/network/parse failure; only a
  failure permits a later open to retry. It no longer fetches on connect. To avoid a
  lost-request race, the player **installs the `transcriptrequested` listener
  immediately after constructing the controller** — before `registerController`
  and before dispatching `cast:player-ready` — so any `requestTranscript()` a view
  fires after subscribing is always observed. (`requestTranscript()` is
  user-triggered on first panel open, well after connect, but the ordering rule
  makes this race-free by construction.)
- `<cast-transcript for="cast-player-{pk}">` — resolves its controller; if
  `controller.hasTranscript` is true it renders the collapsed Transcript button
  even before any cues exist. On the **first** open it calls
  `controller.requestTranscript()` and shows a loading state until `cueschange`.
  It renders cues from controller state, search, speaker labels, highlight,
  follow-along auto-scroll, and seeks on cue activation. **Never fetches.**
- `<cast-chapters for="cast-player-{pk}" data-mode="list|current">` — resolves its
  controller, renders the chapter list (`list`) or a compact current-chapter
  indicator (`current`); seeks on chapter activation. Renders nothing when there
  are no chapters.

### View ↔ controller wiring (registry + lifecycle)

A module-level `Map<string, AudioController>` keyed by player id
(`player-registry.ts`).

- `<cast-audio-player>.connectedCallback`: build controller, `registry.set(id,
  controller)`, then `document.dispatchEvent(new CustomEvent("cast:player-ready",
  { detail: { playerId: id } }))`.
- A view's `connectedCallback`: read `for`, try `registry.get(for)`; subscribe if
  present, else add a `document` listener for `cast:player-ready` and subscribe
  when `detail.playerId === for`, removing the listener once subscribed.
- `disconnectedCallback`: views remove controller listeners and any pending
  `cast:player-ready` listener; the player calls `controller.destroy()` and
  `registry.delete(id)`. Prevents stale controllers leaking across htmx swaps.
- Duplicate ids: `registry.set` over an existing id `console.warn`s and destroys
  the previous controller (last wins). Ids are immutable after connect.

### Public API (one-way readers such as share)

`<cast-audio-player>` exposes, for external consumers only: getters `currentTime`
and `duration`; `getShareState(): {currentTime, duration, audioId}`; and a
bubbling, composed `cast:timeupdate` `CustomEvent` carrying `{currentTime,
duration}`, **throttled to ~4/sec (250 ms)** independent of the internal per-frame
`timeupdate`. The player holds no reference to share UI and nothing in it depends
on share/download/info. This is the only cross-boundary relationship, read-only
and one-directional. (Phase C wires django-chat's share dialog to it.)

The player also reads a `?t=<seconds>` query param on load and seeks once when
metadata is available (`applyStartAt`), giving shared timestamp links a working
receiver side — something Podlove's iframe could not provide.

## Data Transport (revision 4: small inline payload, lazy transcript)

### What ships inline vs. on demand

- **Inline** (`json_script`, on the detail page): `audioId`, `title`, `subtitle`,
  `duration`, `poster`, `sources`, `chapters`, and `transcript` as either
  `{url: "<endpoint>"}` (a transcript exists) or `null` (none). **No transcript
  cues are ever inlined**, regardless of length.
- **On demand** (fetched once by `<cast-audio-player>` after
  `transcriptrequested`): the normalized, sanitized `{cues: [...]}` from the
  endpoint.

This is the core performance change. Detail pages no longer carry the transcript,
and — crucially — the **server no longer builds or sanitizes the full transcript
on every detail-page render**. The inline builder only needs a cheap "does this
audio have a transcript?" check; the expensive cue normalization + public
sanitization happens only when the endpoint is hit (i.e. when a reader actually
opens the transcript).

### Payload builder (backend)

`src/cast/player.py` keeps `build_player_payload(audio, *, post, request,
inline_transcript=True) -> dict`. Revision-4 changes:

- Add a cheap `audio_has_transcript(audio) -> bool` helper (e.g. the audio has a
  related `Transcript` with a non-empty stored `podlove` file) that does **not**
  load/parse/sanitize the file.
- `inline_transcript=True` (the inline `json_script` path): do **not** call
  `build_cues`. Set `transcript = {"url": <fallback endpoint URL>}` when
  `audio_has_transcript(audio)` else `transcript = None`. Drop the
  `CAST_PLAYER_INLINE_TRANSCRIPT_MAX_BYTES` cap logic and the inline cues branch.
- `inline_transcript=False` (the endpoint path): unchanged — call `build_cues`
  and return `{"cues": [...]}`.

The remaining conversions are unchanged from revision 3 and stay correct:

- `audioId` = `audio.pk`; `title` = `audio.title or audio.name or ""`; `subtitle`
  = `audio.subtitle or ""`; `duration` = `int(audio.duration.total_seconds())` or
  `null`; `poster` = cover image URL or `""`, absolutised; `sources` = one entry
  per present format in fixed order (`m4a`/`mp3`/`oga`/`opus`), absolutised;
  `chapters` from `audio.chapters` parsed to `{start: int_seconds, title}` with
  unparseable/empty rows skipped + counted.
- Transcript cue normalization in `build_cues` (sanitized speaker mapping; skip
  cues without a finite `start` or empty `text`; sort by `start`; synthesize a
  finite `end > start` from the next strictly-later cue, else `duration`, else
  `start + 5`; log skipped + synthesized counts) is unchanged — it now runs
  **only** in the endpoint path.

### Inline `json_script` contract

Rendered by the inclusion tag (so the id is computed correctly):

```django
{% cast_custom_player audio post %}
```

renders:

```html
<script type="application/json" id="cast-player-data-123">{ ...PlayerPayload... }</script>
<cast-audio-player id="cast-player-123" data-payload="cast-player-data-123"></cast-audio-player>
```

The tag is `takes_context=True`; it reads `request` from context and calls
`build_player_payload(audio, post=post, request=request)` (needed for absolute
media URLs and the endpoint URL), computes `payload_id` / `player_id`, and emits
JSON with Django's `json_script`-equivalent escaping. One JSON object per audio.

### Lazy hydration flow (revision 4)

1. Detail page renders with `transcript: {url}` (transcript exists) or `null`.
2. `<cast-transcript>` sees `controller.hasTranscript`; renders the collapsed
   Transcript button. No fetch yet.
3. On the **first** open, the view calls `controller.requestTranscript()`.
   The controller sets `transcriptLoading`, emits `transcriptrequested {url}`,
   and the view shows a "Loading transcript…" state (height reserved, no CLS).
4. `<cast-audio-player>` (the only fetcher) fetches the url, with at most one
   request in flight. On success it
   calls `controller.setCues(cues)`, which sets `transcriptLoaded`, clears
   loading, and emits `cueschange`; the view renders cues. On a non-OK/network/
   parse failure it calls `controller.transcriptFailed()`, which clears
   `transcriptLoading` **without** setting `transcriptLoaded` and emits
   `transcripterror`.
5. On `cueschange` the view renders cues. On `transcripterror` the view drops the
   loading state and shows a minimal empty/"transcript unavailable" state (the
   no-JS transcript pages remain the deeper fallback). Because `transcriptFailed()`
   did not set `transcriptLoaded`, a later open re-invokes `requestTranscript()`
   and retries; a successful load sets `transcriptLoaded`, after which re-opening
   never refetches.

### Transcript endpoint contract

DRF view `cast:api:audio_player_transcript` at
`/api/audios/<pk>/player-transcript/`:

- Public read access (`AllowAny`), since the transcript is public content; it
  serves only sanitized cues.
- Accepts `post_id` as a **query parameter** (`?post_id=<pk>`) to establish
  episode/contributor context for sanitization — matching the only routed URL
  `/api/audios/<pk>/player-transcript/` and the `?post_id=` link the builder emits
  (`_fallback_transcript_url`). There is no path `post_id` segment.
- Validates: audio exists; `post_id` references a **live** post the audio belongs
  to; returns 404 otherwise (do not leak unsanitized data for mismatched context).
- Reuses `build_player_payload(..., inline_transcript=False)`'s transcript logic
  and returns `{cues: [...]}` only; never the raw Podlove file.

(This endpoint already exists from revision 3; revision 4 makes it the **only**
transcript source rather than an over-cap fallback.)

## UI Redesign (revision 4)

Target reference: django-chat's thin forest-green Podlove transport (a thin
progress bar with a small thumb and a remaining-time readout) and Able Player's
transcript ergonomics. Structural CSS lives in
`javascript/src/audio/custom-player.css`; colors come from CSS custom properties.

### Transport bar

- **Thinner progress bar.** Reduce the seek-bar track from the current `0.4rem`
  to a thin track (~2–3px) with a small thumb (~10px), matching the django-chat
  look. Keep the accent-filled progress and the `:focus-visible` ring; the thumb
  and focus ring must still survive `forced-colors`.
- **Elapsed + remaining readout.** Replace the single `current / total` `<output>`
  with two readouts: elapsed (`m:ss` / `h:mm:ss`) and remaining
  (`-m:ss` / `-h:mm:ss`, computed as `duration - currentTime`). While duration is
  unknown show elapsed plus `--:--` (or blank) for remaining; on `durationchange`
  fill it in. Time text stays plain (not `aria-live`); the seek slider keeps its
  spoken-time `aria-valuetext` ("12:03 of 1:29:56").
- **Share button** stays as the circular icon button already implemented
  (`openShare()` prefills the start-time from `currentTime`, builds a `?t=` URL,
  copy-to-clipboard, native `<dialog>`).
- **Keyboard-shortcuts affordance (restyled).** Remove the raw
  `<details>"Keyboard shortcuts"</details>` block under the transport. Replace it
  with a small icon button styled like the share button (e.g. a "?" / keyboard
  glyph, `aria-label="Keyboard shortcuts"`) that opens a lightweight popover/
  tooltip listing the shortcuts (native `popover` attribute preferred, with a
  labelled fallback). It must be keyboard-reachable and dismissible.
- Duration-unknown, no-sources, buffering, and "no `aria-pressed` on play/pause"
  behaviors are unchanged from revision 3.

### Collapsible Transcript / Chapters (compact buttons, not full-width panels)

The current full-width `cast-panel` headers (with "Transcript 2640 LINES" /
"Chapters 9" and a chevron) showed cut-off cue text bleeding through the collapsed
state. Replace that with:

- **Ownership (resolves the row question):** there is **no new combined element**
  and the two views stay independent, placeable siblings (preserving the
  persistent-player goal). Each view renders **its own** compact toggle button +
  its own inline-expandable panel. The button is sized to its content (pill-style
  like the Follow button), not full-width. The "controls row" is purely a
  **default-template grouping**: `_custom_player.html` wraps the adjacent
  `<cast-transcript>` and `<cast-chapters>` in a flex container so their two
  buttons read as one row. A theme that relocates the elements simply gets two
  independent compact buttons wherever it places them.
- The **Chapters** button is rendered only when the payload has chapters.
  The **Transcript** button is rendered only when `controller.hasTranscript`.
- **Collapsed state shows no transcript/chapter text at all** — no preview, no
  line/chapter count bleeding through, no layout shift. Any count (e.g. "9
  chapters") moves into the expanded panel's own header, not the collapsed button.
- **Inline expansion.** Activating a button toggles the corresponding panel open
  **inline, below the controls row, in normal page flow** (not a modal overlay).
  `aria-expanded` reflects state; the expanded region is a labelled region with a
  heading and a collapse affordance. Opening Transcript for the first time triggers
  the lazy fetch (above).
- The expanded transcript panel keeps the existing tools (search input + prev/next
  match + match-count status + Follow toggle). The **keyboard-navigable cues
  toggle** moves into this tools row and is styled to match the other controls
  (a labelled pill/segmented toggle), not a bare native checkbox floating at the
  panel edge. It still flips cue `tabindex` between `0`/`-1` and persists in
  `localStorage`.

### Transcript speaker layout

Match the reference (speaker name visually separated from the spoken text, with
indentation):

- Render each **speaker change** as a block label on its own line (uppercase,
  bold, muted/accent color), with the cue text for that turn **indented beneath**
  it. Consecutive cues from the same speaker do not repeat the label and align
  under the same indent.
- Keep per-cue timestamps as a subtle, muted affordance (e.g. a small leading
  timestamp or on-hover), subordinate to the text; do not let the timestamp column
  dominate the layout. Cue text is still rendered via `textContent` only
  (XSS-safe), inside a `<button>` for click-to-seek.

All accessibility contracts from revision 3 (native elements, button names,
`aria-current` not `aria-live` for the current cue, polite search-count status,
focus-scoped keyboard handlers, `prefers-reduced-motion`/`prefers-color-scheme`/
`forced-colors` handling, no positive `tabindex`) remain in force; the redesign
must not regress them.

## Rollout, Settings, Template, and Asset Selection

### Settings

- `CAST_AUDIO_PLAYER`: `"podlove"` (default) or `"custom"`. Unchanged. Registered
  in `src/cast/appsettings.py` and validated by `src/cast/checks.py`
  (`CAST_SETTING_TYPES` + a value check that it is one of `{"podlove", "custom"}`).
- **Removed:** `CAST_PLAYER_INLINE_TRANSCRIPT_MAX_BYTES`. The transcript is always
  lazy-loaded, so there is no inline cap to configure. Remove **every** reference
  (verified present as of this revision):
  - `src/cast/appsettings.py` — the `_DYNAMIC_SETTING_DEFAULTS` entry (`:22`) and
    the `TYPE_CHECKING` annotation (`:40`).
  - `src/cast/checks.py` — the `CAST_SETTING_TYPES` entry (`:30`) and the
    positive-int value check (`:104`, `:109`).
  - `src/cast/player.py` — the cap docstring (`:299`) and the cap branch in
    `build_player_payload` (`:321`), replaced by the `audio_has_transcript` check.
  - `tests/player_test.py` — the cap-related cases (`:286`, `:312`, `:319`, `:397`,
    `:410`, `:415`); replace with the inline-`{url}`/`null` + endpoint-`{cues}`
    tests below.
  - `docs/media/audio-and-transcripts.rst:101` and the **`docs/releases/0.2.59.rst`**
    bullet that introduced the setting. Because `0.2.59` is the in-development
    version (not yet released — see the "Prepare 0.2.59 development version"
    commit), simply remove that bullet rather than writing a deprecation note; the
    setting never shipped, so its removal is not a breaking change.

### Context flags

Detail and list contexts expose two derived booleans (gating asset/preconnect
includes only), produced by `player.py:audio_player_context_flags`:

- `use_podlove_player = enabled and CAST_AUDIO_PLAYER == "podlove"`
- `use_custom_audio_player = enabled and CAST_AUDIO_PLAYER == "custom"`

where `enabled` is the host's existing `use_audio_player or has_audio` condition.

### Player rendering

Decided by the audio block template via `render_detail` / `render_for_feed`:

- `"podlove"`: render the existing Podlove markup, unchanged, where it renders
  today (detail body audio blocks and list cards).
- `"custom"`:
  - Detail render path (`render_detail=True`, not feed): render
    `cast/audio/_custom_player.html` (the inclusion tag + `<cast-audio-player>` +
    the default `<cast-transcript>`/`<cast-chapters>` placement).
  - List cards (`render_detail=False`): render **no audio player** (no inline
    metadata, no JS). The deliberate "fewer players on overview" outcome.
  - Feeds (`render_for_feed=True`): unchanged.

The custom player's JS asset is included only in the detail template, so list
pages never load the player bundle.

### Asset ownership

Built and shipped by **django-cast only**: source in `javascript/src/audio/`,
entry in `javascript/vite.config.ts`, output to `src/cast/static/cast/vite/` via
`just js-build-vite`. All themes include it with the `cast` app:

```django
{% vite_asset 'src/audio/custom-player.ts' app="cast" %}
```

cast-bootstrap5 does not build its own copy; it adds the CSS token mapping and the
detail-template include (gated on `use_custom_audio_player`) and gates its Podlove
preconnect on `use_podlove_player`.

## Theming and CSS Delivery

- CSS lives in `javascript/src/audio/custom-player.css`, imported from the TS
  entry and bundled into the cast Vite output. No TS-injected `<style>`; no Shadow
  DOM.
- Tokens (the **actual** surface the implemented `custom-player.css` defines;
  colors via CSS custom properties with fallbacks): `--cast-player-bg`,
  `--cast-player-surface`, `--cast-player-fg`, `--cast-player-muted`,
  `--cast-player-line`, `--cast-player-mono`, `--cast-player-accent`,
  `--cast-player-on-accent`, `--cast-player-progress-track`, `--cast-player-focus`.
  (`--cast-progress` is an **internal** runtime variable the player sets per frame
  for the fill — not a host theming token.) Revision 4 keeps these token names
  unchanged; the thin-bar redesign is structural CSS only and adds no new host
  token. A `@media (forced-colors: active)` block uses system colors for
  borders/thumb/focus. If the redesign needs a distinct progress-fill color
  separate from `--cast-player-accent`, add the new token here **and** in every
  sibling mapping (cast-bootstrap5, python-podcast, django-chat) in the same change.
- Host mapping: cast-bootstrap5 maps these to its tokens in SCSS (amber accent);
  python-podcast overrides to its purple palette; django-chat (Phase C) maps them
  to its forest-green palette. The player code does not change per site.

## Phase B — python-podcast staging rollout

Goal: serve the custom player on `python-podcast.staging.django-cast.com` while
production (`python-podcast.de`) keeps Podlove, so external Lighthouse / real-
browser testing runs against the custom player.

Findings (python-podcast):

- Deploy is Ansible-driven. Staging host vars
  (`deploy/host_vars/staging.yml`) set `fqdn:
  "{{ project_name }}.staging.django-cast.com"` and `deploy_environment: staging`;
  production host vars set `python-podcast.de`. `deploy/vars.yml` sets
  `django_settings_module: "config.settings.production"` for all hosts (staging
  does **not** override it today — the gap to close).
- Settings are django-environ modules: `config/settings/{base,local,production,
  e2e,test}.py`. There is **no `staging.py` yet**. `local.py` and `e2e.py` already
  set `CAST_AUDIO_PLAYER = "custom"`; production has no override (so it inherits
  the django-cast default `"podlove"`).
- django-cast and cast-bootstrap5 are currently **editable local paths** in
  python-podcast's `pyproject.toml` `[tool.uv.sources]` (for dev). A staging
  deploy installs from those sources, so for staging to pick up the redesigned
  player, the sources must point at a **git ref/branch that contains this work**
  (revert the local editable paths to a git ref before deploying staging), and the
  built Vite assets must be committed/shipped with the django-cast package.

Plan:

1. Add `config/settings/staging.py`:
   ```python
   from .production import *  # noqa: F401,F403

   CAST_AUDIO_PLAYER = "custom"
   ```
2. In `deploy/host_vars/staging.yml`, set
   `django_settings_module: "config.settings.staging"` (production keeps
   `config.settings.production`, Podlove).
3. Point `[tool.uv.sources]` django-cast (and cast-bootstrap5, if its token
   mapping changed) at the git branch holding revision-4 work; rebuild Vite assets;
   deploy staging.
4. Run Lighthouse against `python-podcast.staging.django-cast.com` episode detail
   pages; record performance + accessibility scores into the KPI table and release
   notes. Production is untouched and continues on Podlove.

(Alternative considered: an env-var toggle read in settings. The per-environment
settings module is cleaner here because it matches the existing module-per-
environment pattern and needs no template change. Note the choice in the deploy
docs.)

## Phase C — django-chat adoption (staged, Podlove-look)

Goal: bring the custom player to django-chat, styled to look as close to its
current forest-green Podlove player as practical, wire share to read the player
position, and hide chapters when an episode has none. Stage it first; do not
replace production Podlove.

Findings (django-chat):

- Podlove is integrated via `django_chat/templates/cast/django_chat/audio.html`
  + `player_template.html`, themed by `CAST_PODLOVE_PLAYER_THEMES["django_chat"]`
  in `config/settings/base.py` with tokens including `brand #2d8260`,
  `brandDark #1f6647` (play button / progress), `brandDarkest #14513a`, white text
  on dark-green panels. Site CSS uses `--dc-accent #2d8260` / `--dc-accent-dark
  #14513a`.
- The site's share dialog
  (`django_chat/templates/cast/django_chat/_episode_share_dialogs.html` +
  `static/django_chat/js/share-modal.js`) builds a `?t=<seconds>` link from a
  **manually typed** MM:SS field and does **not** read the player's current
  position; receiver-side auto-seek is explicitly unimplemented because Podlove's
  iframe blocked both postMessage and hash approaches
  (`static/django_chat/js/podlove-loader.js`).
- Deploy is Ansible; `DJANGO_SETTINGS_MODULE` is pinned to
  `config.settings.production`; per-environment values flow through `.env` /
  `deploy/group_vars` (`wagtail_env_extra`). Staging is
  `djangochat.staging.django-cast.com`; production is a placeholder
  (not yet deployed).
- Chapter marks: django-chat episodes do not reliably carry chapters (no local
  chapter import); chapter data, when present, comes from django-cast's models.

Plan:

0. **Template + asset branching (required first — the setting alone does
   nothing).** django-chat overrides the audio template with its own
   `cast/django_chat/audio.html`, which **unconditionally** renders
   `<podlove-player>`, and `episode.html` **unconditionally** loads
   `podlove-player.ts`/`podlove-loader.js`. So `CAST_AUDIO_PLAYER="custom"` will
   not switch django-chat by itself. Phase C must branch these overrides on the
   context flags — mirror the django-cast/cast-bootstrap5 gate: render
   `{% cast_custom_player value page %}` + include `app="cast"` when
   `use_custom_audio_player`, else the existing Podlove markup/assets when
   `use_podlove_player`. (Note django-chat's `audio.html` binds the audio object to
   `value` and the post to `page`, so the tag args are `value page`, not
   `audio post`.) Without this step the rest of Phase C is inert.
1. **Token mapping.** In django-chat's site CSS, map the real player tokens to the
   forest-green palette — `--cast-player-accent: #1f6647` (and/or `#2d8260`),
   `--cast-player-progress-track`, `--cast-player-surface`/`--cast-player-bg`,
   `--cast-player-fg`, `--cast-player-on-accent`, `--cast-player-focus` — so the
   custom player reads like the Podlove player. (Use only tokens that exist in
   `custom-player.css`; there is no `--cast-player-progress` host token — the fill
   color derives from `--cast-player-accent`.) Combine with the thin-bar +
   remaining-time redesign so it visually matches `image 2`.
2. **Screenshot-driven matching.** Use Playwright to screenshot the current
   Podlove player and the custom player on the same episode and iterate on tokens/
   spacing until they read as the same component. Capture before/after screenshots
   in the handoff.
3. **Share integration.** Wire django-chat's existing share dialog to the player's
   read-only API: prefill the start-time from `getShareState().currentTime`
   (and/or subscribe to `cast:timeupdate`) instead of requiring manual entry. The
   player's built-in `?t=` `applyStartAt()` already provides the receiver side
   (no iframe), so remove/replace the "auto-seek not implemented" workaround.
   Decide in code review whether to keep django-chat's dialog (fed by the API) or
   adopt the player's built-in share dialog; default: keep django-chat's dialog,
   feed it from the API, and rely on the player for receiver-side seek.
4. **Conditional chapters.** Rely on the data-driven behavior: the Chapters button
   renders only when chapters exist, so django-chat episodes without chapters show
   no chapters affordance automatically. No new flag is required; add a theme
   opt-out only if a future need to hide present chapters appears (out of scope
   now — note it as a possible follow-up rather than building it).
5. **Staged rollout.** Enable `CAST_AUDIO_PLAYER = "custom"` for django-chat
   **staging only** (via the same env-var/group-vars mechanism, e.g.
   `wagtail_env_extra: { CAST_AUDIO_PLAYER: "custom" }` on the staging group, read
   in settings as `env("CAST_AUDIO_PLAYER", default="podlove")`). Production stays
   on Podlove until the look is signed off.

## Where It Lives, Build, and Test Commands

- **Component source:** `javascript/src/audio/` (controller, player element,
  transcript, chapters, registry, view-base, format, types, css). Entry +
  `vite.config.ts`.
- **Backend:** `src/cast/player.py` (payload builder + `audio_has_transcript`);
  inclusion tag `src/cast/templatetags/cast_audio_player.py`; include
  `src/cast/templates/cast/audio/_custom_player.html`; the gate in
  `cast/audio/audio.html`; the endpoint in `src/cast/api/views.py` +
  `src/cast/api/urls.py`; settings in `src/cast/appsettings.py`; checks in
  `src/cast/checks.py`.
- **Commands:** JS tests `just js-test`; build `just js-build-vite` /
  `just js-build-all`; Python via the repo's pytest invocation; `just check`
  (lint + mypy + 100% coverage) before delivery. Rebuild assets before backend
  tests that render the asset.

## Tests

### vitest (jsdom) — `just js-test`

- **Controller:** play/pause/toggle; `seek` clamping; cue/chapter boundary rules;
  `timeupdate` per-frame coalescing; `durationchange` fills null duration;
  `setCues` installs cues + emits `cueschange`/`cuechange`; **revision 4:**
  `hasTranscript` from `{url}`/`{cues}`/`null`; `requestTranscript()` is
  idempotent (emits `transcriptrequested` once, sets `transcriptLoading`, no
  re-emit after loaded), `setCues` clears loading and sets `transcriptLoaded`;
  listeners add/remove cleanly; `destroy` removes listeners.
- **Transport:** play/pause toggles label/state; range drag/keys call `seek`;
  spoken-time `aria-valuetext`; **revision 4:** elapsed + remaining readout
  (`-mm:ss`), remaining shows `--:--`/blank while duration unknown then fills on
  `durationchange`; no `aria-live` on time; duration-unknown disables range; no-
  sources disabled state; the keyboard-shortcuts affordance is a labelled button
  that opens a dismissible popover (not a raw `<details>`).
- **Lazy transcript (revision 4):** with `transcript: {url}` and the panel
  collapsed, **no fetch** occurs on connect; the Transcript button renders;
  opening the panel the first time calls `requestTranscript()`, the player issues
  exactly **one** fetch and calls `setCues`; the loading state shows then clears;
  re-opening does **not** refetch; `<cast-transcript>` itself never calls `fetch`;
  with `transcript: null` no Transcript button renders.
- **Transcript:** cues render via `textContent` (XSS-safe with a `<script>`-laden
  cue); cue activation seeks; current cue `aria-current` on `cuechange`;
  follow-along auto-scroll respects toggle + reduced-motion; search marks via DOM
  splitting, case-insensitive, text-only, count status, next/prev scroll+focus+
  wrap without seeking; keyboard-navigable toggle flips `tabindex`; **revision 4:**
  speaker rendered as its own block label with indented text (assert the speaker
  label and text are in the expected structure and a repeated speaker is not
  duplicated); empty renders nothing.
- **Chapters:** current chapter on `chapterchange`; activation seeks; empty
  renders nothing (no button); `data-mode` switch.
- **Wiring:** `for=` resolves incl. late `cast:player-ready`;
  `disconnectedCallback` unsubscribes + `destroy`s; duplicate id warns + last
  wins; two players stay independent across an htmx-swap sim.
- **Public API:** getters + `getShareState()`; `cast:timeupdate` throttled ~250
  ms; `?t=` seek-on-load; no reference to share/download/info.

### pytest — backend

- `build_player_payload` shape + conversions (duration/title/subtitle/poster/
  sources/chapters), absolute URLs, chapter time-string parsing, malformed-row
  skipping + logging.
- **Revision 4 transport:** inline path (`inline_transcript=True`) returns
  `transcript: {"url": ...}` when a transcript exists and `transcript: None` when
  not, and **does not build/sanitize cues** (assert `build_cues` is not invoked on
  the inline path, e.g. via a spy/mock, so the perf claim holds); the endpoint path
  (`inline_transcript=False`) still returns normalized, sanitized `{cues: [...]}`.
- Cue normalization (start/end/skip/synthesize, duplicate same-start case,
  sanitization parity, raw `podlove_data` never emitted) — now exercised via the
  endpoint path.
- Endpoint: public read; sanitized `{cues}`; 404 on missing/non-live/mismatched
  `post_id`; never serves the raw Podlove file.
- Rollout gating: `custom` renders the custom markup + `json_script` on the detail
  path and sets `use_custom_audio_player`; `podlove` unchanged; list cards render
  no player; feeds unchanged.
- Settings/checks: `CAST_AUDIO_PLAYER` value check fires on bad input; **assert
  `CAST_PLAYER_INLINE_TRANSCRIPT_MAX_BYTES` is fully removed** (no default, no
  check) and nothing references it.

### Accessibility

Assert ARIA/keyboard contracts directly in vitest (button names, labels, valid
ARIA, no positive `tabindex`, `aria-current`, no `aria-live` on transcript/time,
the restyled shortcuts popover and keyboard-nav toggle are reachable/labelled).
Automated axe is not a v1 dependency; a manual Lighthouse/axe pass runs on the
Phase B staging site.

## Implementation Slices (revision 4)

Already shipped (revisions 1–3, commits `075aa41b`, `effdae09`): backend payload
builder + sanitization parity + settings/checks; transport component + inline JSON
+ rollout gating; chapters view; transcript render/seek/highlight/auto-scroll;
transcript search + keyboard-navigable toggle; the endpoint + (old) over-cap
fallback wiring; cast-bootstrap5 token mapping.

Revision-4 slices (each independently shippable, with tests, behind
`CAST_AUDIO_PLAYER="custom"`):

1. **Lazy transcript transport.** Backend: `audio_has_transcript`, inline path
   returns `{url}`/`null` and stops building cues; remove
   `CAST_PLAYER_INLINE_TRANSCRIPT_MAX_BYTES` + its check. Frontend: controller
   `hasTranscript`/`requestTranscript`/`transcriptrequested`/loading state; player
   fetches on `transcriptrequested` (not on connect); transcript view triggers on
   first open. pytest + vitest.
2. **Transport redesign.** Thin progress bar; elapsed + remaining readout;
   keyboard-shortcuts icon button + popover. vitest + CSS.
3. **Collapsible buttons + speaker layout.** Compact Transcript/Chapters buttons
   (content-width, conditional Chapters, no collapsed preview text), inline
   expansion, count moved into the expanded header; speaker block label with
   indented text; keyboard-nav toggle moved into the tools row and restyled.
   vitest + CSS.
4. **python-podcast staging rollout (Phase B).** `config/settings/staging.py`;
   `host_vars/staging.yml` `django_settings_module`; git-ref sources; deploy;
   run + record Lighthouse.
5. **django-chat adoption (Phase C).** Token mapping to forest-green; Playwright
   screenshot matching; share dialog fed by the player API; staged rollout via
   group-vars env. Production stays on Podlove.

## Persistent Player (future, out of scope here)

Recorded so the component stays persistence-ready: django-cast ships htmx, wraps
content in `#paging-area`, and runs View-Transition swaps for pagination. A future
spec can promote the single controller to one persistent player by relocating
`<cast-audio-player>` to a `<body>`-level region outside `#paging-area`, extending
boosting to link navigation (`hx-boost`), and driving the one global player by
`for=` id. Keep the controller UI-agnostic, key views by id, register/clean up
precisely, and keep the public contract stable so promotion needs no rewrite.
The concrete python-podcast staging PRD/spec now lives in
`2026-06-08-persistent-player-staging.md`.

## Sibling Repo Impact

- `../cast-bootstrap5`: maps the player CSS tokens in SCSS; includes the
  django-cast-built asset via `app="cast"` (detail template), gated on
  `use_custom_audio_player`. No model/API change, no duplicate JS build.
- `../python-podcast`: end-to-end validation site; Phase B adds `staging.py` +
  `host_vars/staging.yml` change for the staging Lighthouse run; production
  unchanged.
- `../django-chat`: Phase C — token mapping, share-dialog API wiring, staged
  `CAST_AUDIO_PLAYER="custom"`; production stays on Podlove.
- `../cast-vue`: unaffected (the `podlove_players` API path is a separate consumer
  and out of scope).

## Documentation and Release Notes

- Update `docs/media/audio-and-transcripts.rst`: the custom player,
  `CAST_AUDIO_PLAYER`, the **removal** of `CAST_PLAYER_INLINE_TRANSCRIPT_MAX_BYTES`
  and the move to always-lazy transcript loading, the theming token surface, and
  the `cast:api:audio_player_transcript` endpoint.
- Update the in-progress release note (`docs/releases/<current-version>.rst`) for
  the redesign + lazy-load + removed setting, including the KPI numbers
  (~10 KB gzip vs ~138 KB Podlove). Confirm the removed setting was never in a
  released version before describing it as non-breaking.
- Document the theming contract for cast-bootstrap5 / python-podcast / django-chat
  consumer sites and the Phase B/C rollout mechanics.
- Keep `BACKLOG.md` and this note in sync with the repo state when committing.

## Decisions (revision 4)

- **Transcript is always lazy-loaded on first panel open**; never inlined.
  `CAST_PLAYER_INLINE_TRANSCRIPT_MAX_BYTES` is removed. The inline builder does a
  cheap has-transcript check and never sanitizes cues per page render.
- **Time readout is elapsed + remaining** (`12:03 … -51:01`), Podlove-style.
- **Collapsed Transcript/Chapters are compact content-width buttons** that expand
  **inline**; no collapsed preview text; Chapters shown only when chapters exist.
- **One spec, phased**: django-cast redesign (Phase A) + python-podcast staging
  (Phase B) + django-chat adoption (Phase C) live in this note.
- `preload="metadata"` default; chapter `href`/`image` omitted in v1; element
  names `cast-audio-player`/`cast-transcript`/`cast-chapters`, `cast:` event
  namespace — all unchanged.
- No-JS fallback unchanged: the public transcript pages
  (`cast/plain/transcript.html`, `cast/bootstrap4/transcript.html`) and the
  transcript file endpoints remain the no-component path.

## Success Criteria

- With `CAST_AUDIO_PLAYER="custom"`, the detail path renders the custom player (no
  iframe, no facade); the default `"podlove"` changes nothing; list cards render no
  player; feeds and the cast-vue path are untouched.
- **Detail-page HTML carries no transcript cues** for any episode size; the server
  does not build/sanitize the transcript on detail-page render; the transcript is
  fetched from the sanitized endpoint only on first open of the Transcript panel,
  with at most one request in flight and no refetch after a successful load (a
  failed load may retry on a later open); non-public speakers never leak; raw
  `podlove_data` is never emitted.
- Transport (play/pause, thin draggable seek bar, elapsed + remaining time,
  duration-unknown handling, share-with-position, `?t=` seek, restyled
  keyboard-shortcuts affordance), transcript (compact button → inline expand,
  speaker block layout with indented text, search, highlight, follow-along,
  click-to-seek, drag-to-jump, XSS-safe rendering), and chapters (conditional
  button, current marker, click-to-seek) all work and stay in sync via the shared
  controller.
- The transcript element renders correctly when placed away from the transport bar.
- Show notes/info, download, and share remain independent; the player only exposes
  a read-only position API and honours `?t=`.
- Zero runtime dependencies; themed entirely via CSS custom properties; correct in
  light, dark, and forced-colors modes; combined shipped bytes ≤ ~12 KB gzip.
- vitest covers controller, transport, lazy-load, transcript, chapters, wiring,
  public API; pytest covers the payload builder, the inline-vs-endpoint transcript
  split, sanitization parity, endpoint validation, rollout gating, and
  settings/checks (including the removed cap). `just check` and `just js-test` pass.
- `CAST_PLAYER_INLINE_TRANSCRIPT_MAX_BYTES` is fully removed with no dangling
  references.
- **Phase B:** `python-podcast.staging.django-cast.com` serves the custom player
  while production stays on Podlove; external Lighthouse scores are recorded.
- **Phase C:** django-chat staging serves the custom player styled to match its
  Podlove look (screenshot evidence), its share dialog reads the player position
  and shared `?t=` links seek on the receiver, chapters are hidden when absent, and
  production remains on Podlove.
- `docs/media/audio-and-transcripts.rst` and the release note describe the lazy
  transcript, the removed setting, the theming tokens, the endpoint, the KPIs, and
  the staging/django-chat rollout.
