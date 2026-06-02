# Custom Audio Player Web Component (Transport + Transcript + Chapters)

## Status

Planned. Not yet implemented. This note is the design spec for replacing the
third-party Podlove Web Player with a small, dependency-free custom audio player
whose only coupled responsibilities are playback transport, an interactive
transcript, and chapter navigation.

Review history:

- Round 1 (`pi`): NEEDS REVISION — addressed in revision 2.
- Round 2 (`pi` + an independent reviewer): NEEDS REVISION. This revision (3)
  fixes the rollout-flag formula (detail pages use `has_audio`, not
  `use_audio_player`), the list-page render decision, the audio render-path scope
  (standalone `Episode.podcast_audio` is cast-vue/API-only and out of scope),
  settings/system-check integration, the invalid `json_script`
  filter expression, the raw-vs-sanitized transcript-storage wording, the
  fallback hydration ownership, asset/app ownership for cast-bootstrap5, concrete
  boundary/empty/duration/search semantics, the public fallback-endpoint
  contract, and documentation/release-note requirements. Remaining "open
  questions" that were really decisions are now decided.

The current player is the Podlove Web Player v5, integrated as:

- `javascript/src/audio/podlove-player.ts` — a vanilla `HTMLElement` wrapper that
  lazy-loads Podlove's `embed.5.js` via a facade (IntersectionObserver) or a
  click-to-load button.
- `src/cast/templates/cast/audio/audio.html` — renders `<podlove-player>` with
  `data-url`, `data-config`, `data-embed`, and a `podlove_load_mode`-driven
  facade/click gate. The template is selected by `AudioChooserBlock.get_template`
  via `get_block_template(..., file_name="audio.html")`
  (`src/cast/blocks.py:426-429`), so themes can override it by `template_base_dir`.
- On **server-rendered** themes (plain, bootstrap5, python-podcast), the player is
  rendered by the StreamField `audio` block via `audio.html` —
  `post_body.html` iterates `page.body` and calls `{% include_block block %}`
  (`src/cast/templates/cast/bootstrap4/post_body.html:21-27`). The episode's audio
  appears as a body `audio` block; that block is the only server render path for a
  web player. `Episode.podcast_audio` as a standalone field is surfaced separately
  through `podlove_players` (a Wagtail API field, `src/cast/models/pages.py:900-913`)
  consumed by the **cast-vue SPA**, not by server templates — that path is out of
  scope here. The detail context exposes `has_audio`
  (`src/cast/models/pages.py:343-356`): true when the post has audio in its body or
  any `Post.audios`, falling back to `Episode.podcast_audio is not None` for
  episodes. List/index contexts expose `use_audio_player`
  (`src/cast/models/repository/contexts.py:393-400, 461-482, 535-552`).
- API: `src/cast/api/serializers.py` (`AudioPodloveSerializer`) returns an inline
  `transcripts` field — a list of segments, **not** a transcript URL
  (`src/cast/api/serializers.py:44, 124-127`) — and applies public speaker
  sanitization in `to_representation` (`:62-69`,
  `src/cast/transcript_sanitization.py:333+`). A separate raw Podlove transcript
  file endpoint exists at `cast:podlove-transcript-json`
  (`src/cast/urls.py:26`); it serves the stored file shape and is not reused here.
- `src/cast/podlove.py` builds the Podlove theme/config JSON.

Note: stored transcript data is **raw**. `Transcript.podlove_data`
(`src/cast/models/transcript.py:233`) reads the stored file directly with no
sanitization; sanitization happens only on public output in the serializer/views.
The custom payload builder must therefore run transcript data through the public
sanitization path, never read `podlove_data`/`transcript.podlove.url` directly for
public output.

Project conventions: this repo uses `AGENTS.md` (there is no `CLAUDE.md`); docs
and release notes must be updated in the same change when user-facing behavior
changes.

## Summary

Build a custom, self-rendering audio player as **vanilla TypeScript Web
Components** (no runtime dependencies) that replaces Podlove on the episode detail
page. The player gets the data it needs **inlined into the page as JSON**
(`json_script`); for normal-length episodes it renders with **no runtime fetch for
the transcript** and **no hover/click-to-load facade**. It renders immediately,
looks plain, adapts to the host site's colors via CSS custom properties (light and
dark), and is engineered for top Lighthouse performance and accessibility scores.

A single **audio controller** (one `<audio>` element plus playback state) is the
single source of truth. Three views are bidirectionally coupled to it and are in
scope:

1. **Transport UI** — play/pause, draggable/seekable progress bar, current/total
   time. No volume control, no playback-speed control.
2. **Transcript** — speaker identification, in-transcript search, current-cue
   highlight, auto-scroll following playback, click-a-cue-to-seek, and
   drag-the-bar-jumps-the-transcript. Placeable anywhere on the detail page.
3. **Chapters** — show the current chapter during playback and seek when a
   different chapter is selected.

Everything else — show notes / info, download, share/embed — is explicitly **out
of scope** and remains an independent page concern. The player neither contains
nor triggers them. The one allowed relationship is one-directional: external share
UI may **read** the player's current position through a small public API. The
player never depends on share, download, or info.

The player is built **dual-mode**: it works standalone today (on the episode
detail page), and the same audio controller is designed to be promotable later to
a single **persistent player** that keeps playing across page navigation. The
persistence layer (htmx `hx-boost`, relocating the player outside `#paging-area`)
is a deliberate follow-up and is **not** part of this spec.

## Problem

The Podlove Web Player is a ~138 KB Vue app rendered inside an iframe, causing:

- **Styling ceiling.** Podlove bakes styling into inline `style` attributes set by
  Vue at runtime and does not emit CSS custom properties; DOMPurify strips injected
  `<style>`. `../django-chat` documents (in
  `2026-05-17-player-restyling-research.md`) that matching the player to site
  branding — even fixing dark-text-on-dark-background contrast — is effectively
  impossible from outside the iframe.
- **Load cost and the facade.** Because the player is heavy, integrations gate it
  behind a hover/click facade (`podlove_load_mode`). This is exactly the
  "tab/hover to load" behavior we want to remove.
- **Runtime data fetch.** The player fetches episode JSON, transcript segments, and
  config at runtime, adding requests and latency.
- **Many players per page.** Overview/list pages render multiple players, which
  does not make sense and multiplies cost.

The backend already produces the underlying data:

- `Transcript` (`src/cast/models/transcript.py`) stores a Podlove-format JSON
  transcript whose cues are `{start, start_ms, end, end_ms, speaker, voice,
  text}`, plus `.vtt` and `.dote` variants. Upload validation only guarantees a
  top-level `transcripts` list (`src/cast/forms.py:245`), so per-cue fields must be
  treated as best-effort and normalized defensively. Stored data is raw
  (unsanitized).
- `Audio` (`src/cast/models/audio.py`) stores `duration` (nullable
  `DurationField`, `:52`), `title` (nullable, `:53`), `subtitle` (`:54`), formats
  `m4a`/`mp3`/`oga`/`opus` (`:67-70`) with a MIME lookup (`:74-79`), and exposes
  `chapters` from `ChapterMark` rows where `start` is a **time string**, not
  seconds (`:207-219`, `:379-388`).
- `AudioPodloveSerializer` assembles audio formats, chapters, transcript segments,
  contributors, and show metadata, and applies public speaker sanitization on
  output.

So the work is a frontend replacement plus a data-transport change (a dedicated,
sanitized, normalized inlined payload instead of a runtime Podlove fetch). The data
**model** is reused; the Podlove-shaped API payload is **not**.

## Rollout, Settings, Template, and Asset Selection

### Settings

Add two settings, registered in `src/cast/appsettings.py` `_DYNAMIC_SETTING_DEFAULTS`
(and the `TYPE_CHECKING` block):

- `CAST_AUDIO_PLAYER`: `"podlove"` (default) or `"custom"`.
- `CAST_PLAYER_INLINE_TRANSCRIPT_MAX_BYTES`: `int`, default `150_000`.

Validate them via `src/cast/checks.py`: add to `CAST_SETTING_TYPES`
(`("CAST_AUDIO_PLAYER", str)`, `("CAST_PLAYER_INLINE_TRANSCRIPT_MAX_BYTES", int)`)
and add a value check (an `@register("cast")` check alongside
`check_cast_setting_types`) that `CAST_AUDIO_PLAYER` is one of
`{"podlove", "custom"}` and that `CAST_PLAYER_INLINE_TRANSCRIPT_MAX_BYTES` is an
`int` that is **not** a `bool` (note `isinstance(True, int)` is `True`) and is
`> 0`.

### Context flags

Both the detail and list contexts must expose two derived booleans so themes can
switch preconnect/asset includes. They mirror the condition cast-bootstrap5 already
uses to load the Podlove asset (`use_audio_player or has_audio`):

- `use_podlove_player = (use_audio_player or has_audio) and CAST_AUDIO_PLAYER == "podlove"`
- `use_custom_audio_player = (use_audio_player or has_audio) and CAST_AUDIO_PLAYER == "custom"`

Set these wherever `has_audio` (detail, `src/cast/models/pages.py:404`) and
`use_audio_player` (list, `contexts.py`) are set, so both contexts carry them.
These gate **asset/preconnect includes only**.

### Player rendering (resolves the list-page decision)

Player *rendering* is decided separately from the asset flags, by the audio block
template, which already receives `render_detail` (`True` on detail via
`post.html` → `post_body.html with render_detail=True`; `False` on list cards, e.g.
`blog_list_of_posts.html`) and `render_for_feed`:

- `CAST_AUDIO_PLAYER == "podlove"`: render the existing Podlove markup, unchanged,
  exactly where it renders today (detail body audio blocks and list cards).
- `CAST_AUDIO_PLAYER == "custom"`:
  - On the detail render path (`render_detail=True`, not `render_for_feed`):
    render the custom player (`cast/audio/_custom_player.html`) plus the inlined
    `json_script`.
  - On list cards (`render_detail=False`): render **no audio player** (no inline
    transcript, no chapters, no JS). The list card keeps its existing cover/title/
    link layout. This is the deliberate "fewer players on overview" outcome.
  - Feeds (`render_for_feed=True`): unchanged (no web player).

Because the custom player only renders on the detail path, and its JS asset is
included only in the detail template (`post.html`), list pages never load the
player bundle even though `use_custom_audio_player` may be true there.

The custom player replaces Podlove at the **StreamField `audio` block** render path
on server-rendered themes (`audio.html` → `_custom_player.html`) — the location
Podlove renders on server pages. The cast-vue SPA's `podlove_players` API path
(standalone `Episode.podcast_audio` not embedded in the body) is a separate consumer
and is out of scope; `../cast-vue` is unaffected. This spec adds no server render
path for a standalone `podcast_audio`; episode audio reaches server templates only
as a body `audio` block.

### Asset ownership (single source of truth)

The component is built and shipped by **django-cast only**: source in
`javascript/src/audio/custom-player.ts`, a new entry in
`javascript/vite.config.ts`, output to `src/cast/static/cast/vite/` via
`just js-build-vite`. All themes — including cast-bootstrap5 — include it with the
**`cast` app**:

```django
{% vite_asset 'src/audio/custom-player.ts' app="cast" %}
```

cast-bootstrap5 does **not** build its own copy; it only adds the CSS token mapping
and the (detail-template) include, gated on `use_custom_audio_player`, and gates
its Podlove preconnect on `use_podlove_player`.

## Architecture

### Audio controller (single source of truth)

A framework-free `AudioController` owns one `HTMLAudioElement` and the playback
state. It **extends `EventTarget`** (platform-native pub/sub) — no custom reactive
store / signals library, to keep shipped JS minimal. The same pub/sub is reused
unchanged by the future persistent player.

TypeScript surface (normative shape; names may be refined in code review):

```ts
type Cue = { start: number; end: number; speaker: string; text: string };
type Chapter = { start: number; title: string };
type PlayerPayload = {
  audioId: number;
  title: string;
  subtitle: string;
  duration: number | null;      // seconds; null if unknown until metadata loads
  poster: string;               // "" if none
  sources: { type: string; src: string }[];
  chapters: Chapter[];
  transcript:
    | { cues: Cue[] }            // inline (normal case)
    | { url: string };          // fallback for over-cap transcripts
};

class AudioController extends EventTarget {
  constructor(audio: HTMLAudioElement, payload: PlayerPayload);

  get currentTime(): number;            // seconds
  get duration(): number | null;        // payload.duration ?? audio.duration (if finite)
  get paused(): boolean;
  get currentChapterIndex(): number;    // -1 if none
  get currentCueIndex(): number;        // -1 if none / not loaded

  play(): Promise<void>;                // swallows AbortError; emits "error" on real failure
  pause(): void;
  toggle(): void;
  seek(seconds: number): void;          // clamped to [0, duration ?? audio.duration ?? seconds]
  seekToCue(index: number): void;       // seek(cue.start + 0.01)
  seekToChapter(index: number): void;

  setCues(cues: Cue[]): void;           // installs cues (fallback path), recomputes
                                        // currentCueIndex, emits "cueschange" then
                                        // "cuechange" if the index changed

  destroy(): void;                      // removes audio listeners, pauses, clears state
}
```

Events (`CustomEvent` on the controller; `detail` noted): `play`, `pause`;
`timeupdate` `{currentTime, duration}` **coalesced to one dispatch per animation
frame**; `durationchange` `{duration}`; `seeking`/`seeked` `{currentTime}`;
`chapterchange` `{index}`; `cuechange` `{index}`; `cueschange` `{count}`; `error`
`{error}` (real load/playback failure, not play-interrupt).

Boundary/normalization rules (the controller assumes the builder delivers cues
sorted by `start`; it does not re-sort):

- A cue is current when `cue.start <= t < cue.end` (inclusive start, **exclusive
  end**). At an exact `t == cue.end`, that cue is not current.
- Gaps: if no cue satisfies the rule, `currentCueIndex = -1`.
- Overlaps: if multiple cues satisfy the rule, the **last** such cue (highest
  index) wins.
- Chapters: a chapter is current when `chapter.start <= t < next.start`; the last
  chapter extends to the end. No current chapter before the first chapter's start →
  `-1`.
- Ended (`t >= duration`, and on the `ended` media event): an **explicit exception**
  to the exclusive-end rule — keep the last cue and last chapter highlighted
  (`currentCueIndex = cues.length - 1`, `currentChapterIndex = chapters.length - 1`)
  so the transcript/chapter does not blank out at the very end. Empty cues/chapters
  → `-1`.
- Duration source: `payload.duration` if non-null; else `audio.duration` once it is
  a finite number (after `durationchange`); else `null`. `seek` clamps with the
  best known finite duration, otherwise only clamps the lower bound at 0.
- Malformed cues never reach the controller — the backend builder skips them (see
  Data Transport); the controller treats its input as already-normalized.

### Web components (views)

Custom elements extending `HTMLElement`, `cast-` prefixed, in
`javascript/src/audio/`. **Light DOM** (no Shadow DOM) so host CSS custom
properties cascade in and Lighthouse can audit the controls.

- `<cast-audio-player id="cast-player-{pk}" data-payload="cast-player-data-{pk}">` —
  reads the inlined JSON by `data-payload` id, builds the `<audio>` element and the
  `AudioController`, registers it, and renders the transport UI. **Owns** all data
  parsing and (for the fallback) all transcript fetching.
- `<cast-transcript for="cast-player-{pk}">` — resolves its controller, renders cues
  from controller state, search, speaker labels, highlight, auto-scroll; seeks on
  cue activation. **Never fetches**; it only reads controller cues.
- `<cast-chapters for="cast-player-{pk}" data-mode="list|current">` — resolves its
  controller, renders the chapter list (`list`) or a compact current-chapter
  indicator (`current`); seeks on chapter activation.

### View ↔ controller wiring (registry + lifecycle)

A module-level `Map<string, AudioController>` keyed by player id.

- `<cast-audio-player>.connectedCallback`: build controller, `registry.set(id,
  controller)`, then `document.dispatchEvent(new CustomEvent("cast:player-ready",
  { detail: { playerId: id } }))`.
- A view's `connectedCallback`: read `for`, try `registry.get(for)`; subscribe if
  present, else add a `document` listener for `cast:player-ready` and subscribe
  when `detail.playerId === for`, removing the listener once subscribed.
- `disconnectedCallback`: views remove controller listeners and any pending
  `cast:player-ready` listener; the player calls `controller.destroy()` and
  `registry.delete(id)`. Prevents stale controllers leaking across htmx swaps.
- Duplicate ids: `registry.set` over an existing id `console.warn`s and destroys the
  previous controller (last wins). Ids are immutable after connect (no render path
  needs runtime id/`for` changes).

### Public API (one-way readers such as share)

`<cast-audio-player>` exposes, for external consumers only: getters `currentTime`
and `duration` (seconds; `duration` may be `null`); `getShareState(): {currentTime,
duration, audioId}`; and a bubbling, composed `cast:timeupdate` `CustomEvent`
carrying `{currentTime, duration}`, **throttled to ~4/sec (250 ms)** independent of
the internal per-frame `timeupdate`. The player holds no reference to share UI and
nothing in it depends on share/download/info. This is the only cross-boundary
relationship, read-only and one-directional.

## Data Transport (inline JSON, sanitized, with fallback)

### Payload builder (backend)

A new module `src/cast/player.py` exposes
`build_player_payload(audio, *, post, request, inline_transcript=True) -> dict`
returning the normalized `PlayerPayload`. It is **separate** from
`AudioPodloveSerializer` and **not** Podlove-compatible. Exact conversions:

- `audioId`: `audio.pk`.
- `title`: `audio.title or audio.name or ""`.
- `subtitle`: `audio.subtitle or ""` (the model field that exists,
  `src/cast/models/audio.py:54` — not a `Post`/`Episode` field).
- `duration`: `int(audio.duration.total_seconds())` if `audio.duration` else
  `null` (the component fills it from media metadata).
- `poster`: post/page cover image URL, else blog cover image URL, else `""`
  (audio blocks can live on non-Episode posts; do not assume an episode cover);
  absolutised with `request.build_absolute_uri`.
- `sources`: one entry per present format in fixed preference order
  (`m4a`→`audio/mp4`, `mp3`→`audio/mpeg`, `oga`→`audio/ogg`, `opus`→`audio/opus`),
  each `src` absolutised. Omit missing formats.
- `chapters`: from `audio.chapters`, mapped to `{start: int_seconds, title}`.
  `audio.chapters` `start` is a **time string** (`HH:MM:SS`/`MM:SS`); parse to
  integer seconds. Skip rows with an unparseable `start` or empty `title` and log
  the skipped count. `href`/`image` are omitted in v1.
- `transcript.cues`: **must use the public sanitization path**, not raw storage.
  Take the sanitized segments via the same helper the serializer uses
  (`src/cast/transcript_sanitization.py`, as called in
  `AudioPodloveSerializer.to_representation`), passing the correct episode/post
  context. Normalize each sanitized segment to `{start, end, speaker, text}`. The
  controller contract requires every emitted cue to have a finite `start` and a
  finite `end > start` (it uses `start <= t < end`), but upload validation only
  guarantees a top-level `transcripts` list (`src/cast/forms.py:245`), so per-cue
  fields are best-effort and must be normalized defensively:
  - **start:** prefer `start_ms` (→ seconds, `/1000`); else parse the `start` time
    string. If neither yields a finite number, **skip the cue and count it**.
  - **text:** required; **skip + count** if empty/whitespace.
  - **speaker:** the sanitized/mapped display name, else `""`.
  - After collecting all cues with a finite `start` and non-empty `text`, **sort by
    `start`**.
  - **end (synthesized, never drops valid text):** prefer `end_ms` (→ seconds);
    else parse the `end` time string. If the parsed `end` is missing, non-finite,
    or `<= start`, set `end` to the **start of the next cue whose `start` is
    strictly greater** than this cue's start (skipping any same-start cues, so the
    result is always `> start`); if no later-start cue exists, set `end = duration`
    when a finite `duration > start` is known, else `start + 5` (a 5-second
    default). This guarantees a finite `end > start` for every emitted cue —
    including duplicate/same-start cues — without discarding transcript text for a
    bad/missing end value. (Same-start cues are a valid overlap shape; the
    controller's "last matching cue wins" rule then applies.)
  - Log the skipped-cue count (cues dropped for missing `start` or empty `text`)
    and, separately, the synthesized-`end` count.

The same builder feeds both the inline `json_script` (with cues) and the fallback
endpoint (cues only).

### Inline `json_script` contract

Rendered by a custom inclusion tag (so the id is computed correctly — note the
naive `payload|json_script:"..."|add:pk` filter chain does **not** work, because
`add` would apply to the rendered `<script>` output, not the id argument):

```django
{% cast_custom_player audio post %}
```

which renders exactly:

```html
<script type="application/json" id="cast-player-data-123">{ ...PlayerPayload... }</script>
<cast-audio-player id="cast-player-123" data-payload="cast-player-data-123"></cast-audio-player>
```

The tag is `takes_context=True`: it reads `request` from the template context and
passes it to `build_player_payload(audio, post=post, request=request)` (needed for
absolute media URLs and the fallback endpoint URL). It computes `payload_id =
f"cast-player-data-{audio.pk}"` and `player_id = f"cast-player-{audio.pk}"`, and
emits the JSON with Django's `json_script`-equivalent escaping. One JSON object per
audio carries metadata, chapters, and (normally) transcript cues — not separate
scripts.

**Default element placement.** `_custom_player.html` renders, by default, the
`json_script` + `<cast-audio-player>` followed immediately by
`<cast-transcript for="cast-player-{pk}">` and `<cast-chapters
for="cast-player-{pk}" data-mode="list">`, so the full feature works out of the box
in django-cast's own themes (plain/bootstrap4). `<cast-transcript>`/`<cast-chapters>`
read their data from the controller (not the DOM JSON), so a theme can **relocate**
them anywhere on the detail page by moving those elements (keeping the same `for=`
id) — e.g. cast-bootstrap5/python-podcast may place the transcript in a wide column
below the body while the transport bar stays at the top. Slice 4/5 define the
cast-bootstrap5 default placement.

### Size cap and sanitized fallback

`CAST_PLAYER_INLINE_TRANSCRIPT_MAX_BYTES` (default `150_000`) bounds the inlined
transcript, measured as the byte length of the JSON-serialized **cues array**:

- Under the cap (normal episodes): `transcript: {cues: [...]}` inlined; no fetch.
- Over the cap: the builder sets `transcript: {url: "<fallback endpoint URL>"}`,
  omits cues, and the inclusion tag **logs** the fallback.
- Hydration ownership is unambiguous: when the payload has `transcript.url`,
  `<cast-audio-player>` (the controller owner) constructs the controller with **no
  cues** (`currentCueIndex = -1`), fetches the URL **once** after construction,
  and calls `controller.setCues(cues)`. `setCues` emits `cueschange` (and
  `cuechange` if the index changed); `<cast-transcript>` shows a minimal loading
  state until then. `<cast-transcript>` never fetches.
- The fallback endpoint returns **normalized, sanitized `{cues: [...]}`** — the
  same shape and sanitization as the inline path — **not** raw Podlove JSON.

### Fallback endpoint contract

New DRF view `cast:api:audio_player_transcript` at
`/api/audios/<pk>/player-transcript/` (exact route name confirmed in slice 6):

- Public read access (`AllowAny` / matching the public episode pages), since the
  transcript is public content; it serves only sanitized cues.
- Accepts `post_id` (query or path) to establish episode/contributor context for
  sanitization, exactly as the inline builder does.
- Validates: audio exists; `post_id` references a **live** post the audio belongs
  to; returns 404 otherwise (do not leak unsanitized data for mismatched context).
- Reuses `build_player_payload(..., inline_transcript=True)`'s transcript logic and
  returns `{cues: [...]}` only.

## Transport UI Behavior

- **Play/pause:** native `<button>`; accessible name swaps Play↔Pause on state
  change; icon SVG is `aria-hidden`. No `aria-pressed`.
- **Seek bar:** native `<input type="range">`, `min=0`, `step=1`, styled plain/
  themeable, draggable + keyboard-operable for free. `aria-label="Seek"` and a
  dynamically updated spoken-time `aria-valuetext`. A visible `<output>` shows
  current/total time (`m:ss` / `h:mm:ss`).
- **Duration unknown** (`payload.duration` null until media metadata loads): the
  range is **disabled** with `max=0` and the time display shows `--:--` for total;
  `aria-valuetext` reads "duration unknown". On `durationchange`, set `max`,
  enable the range, and update the display. Position/seek still work via the media
  element once metadata arrives.
- **No sources** (empty `sources`): render the player in a disabled state with a
  visible "audio unavailable" message; do not register keyboard shortcuts.
- **Dragging the bar** drives `controller.seek`, updating chapter + transcript
  highlight/scroll.
- **No volume, no speed** in v1.
- **Buffering:** minimal state without layout shift (reserve control dimensions).

## Transcript Behavior

Modeled on Able Player (the accessibility reference).

- **Cues:** each cue is a native `<button>` with `data-start`/`data-end`, text
  rendered via `textContent` (never `innerHTML`). Speaker labels in a separate
  `<span class="cast-transcript__speaker">`.
- **Tab-stops (explicit decision):** cue buttons are **not in the tab order by
  default** (`tabindex="-1"`) — with long transcripts, tabbing every cue is hostile.
  They stay mouse/touch click-to-seek. Keyboard users seek via the transport slider
  and via search + next/prev-match. A labeled "Keyboard-navigable transcript"
  checkbox flips cues to `tabindex="0"` (Able Player's opt-in `prefTabbable`); the
  toggle state persists in `localStorage`.
- **Click-to-seek:** activating a cue calls `controller.seekToCue(index)`.
- **Current-cue highlight:** active cue gets `aria-current="true"` + a visual class.
  Visual only — **no `aria-live`** on the transcript, so the SR is not flooded.
- **Auto-scroll:** keep the current cue in view via `scrollIntoView`, `behavior:
  'smooth'` only when `prefers-reduced-motion` is unset, else `'auto'`. A labeled
  "Auto-scroll" checkbox (default on). Never move focus on highlight change (only on
  explicit click).
- **Search:** a labeled `<input>`. Behavior: **case-insensitive, accent-sensitive**
  substring match over **cue text only** (not speaker labels) in v1; non-matching
  cues stay visible (**mark, don't hide**); matches wrapped in `<mark>` built via DOM
  node splitting (never `innerHTML`). A `role="status"` `aria-live="polite"` region
  announces the count. Next/previous-match buttons (labeled) **scroll and focus** the
  match and **wrap** at the ends; they do **not** seek playback (seeking stays an
  explicit cue activation). No focus trap.
- **Empty/missing transcript:** no cues and no `url` → render nothing (no empty box,
  no layout shift). With `url` → minimal loading state (reserve height) until
  `setCues`.
- **Two-way coupling:** playback drives highlight + scroll; cue activation drives
  playback; dragging the transport bar drives highlight/scroll.

## Chapters Behavior

- `data-mode="list"`: chapters as native `<button>`s (each seeks). Current chapter
  (from `chapterchange`) marked with `aria-current` + a class.
- `data-mode="current"`: a compact current-chapter text indicator.
- Activation calls `controller.seekToChapter(index)`, updating the bar + transcript.
- No chapters → render nothing (no empty box, no layout shift).

## Accessibility Requirements

Prefer native elements (`<button>`, `<input type="range">`, `<input
type="checkbox">`) so keyboard, focus, and roles come for free.

- **Buttons:** native; icon-only buttons carry an accessible name via `aria-label`;
  decorative SVGs `aria-hidden`. (Lighthouse `button-name`.)
- **Play/pause:** label swaps; no `aria-pressed`.
- **Seek slider:** native range with `aria-label` + spoken-time `aria-valuetext`;
  visible focus ring; thumb/border survive forced-colors.
- **Time display:** plain text, **not** `aria-live`. Play/pause/buffering state via a
  single shared `role="status"` `aria-live="polite"` region.
- **Transcript:** cues are buttons with the tab-stop decision above; current cue uses
  `aria-current`, not `aria-live`; auto-scroll and keyboard-navigable toggles are
  labeled checkboxes; search count via a polite status region; the transcript is a
  labeled region with a heading.
- **Keyboard shortcuts:** handlers scoped to focus within the player (attached to the
  player root, not `document`). Never `preventDefault` on Space/arrows unless the
  target is one of our controls (preserve native range/button behavior). Default
  focus-scoped keys: Space/K = play/pause (when the target is not the range, which
  already uses Space), ArrowLeft/Right = seek ∓5s (when the target is not the range,
  which handles its own arrows), Home/End = start/end. v1 ships focus-scoped only;
  any future page-global shortcut must require a modifier and be documented. Provide
  a discoverable shortcuts list.
- **Throttling:** highlight/scroll DOM updates and the public `cast:timeupdate` event
  are throttled (per-frame internal coalescing; 250 ms public event).
- **Focus & motion:** visible `:focus-visible` outlines (≥3:1 contrast); honor
  `prefers-reduced-motion`, `prefers-color-scheme`, `forced-colors`; never convey
  state by color alone (pair with `aria-current`/icon/text).

Target: zero Lighthouse accessibility audit failures (`button-name`,
`color-contrast`, `label`, `aria-*` validity, `aria-required-children/parent`, no
positive `tabindex`).

## Theming and CSS Delivery

- **Where CSS lives:** the component imports a plain CSS file
  (`javascript/src/audio/custom-player.css`) from its TS entry; Vite bundles it into
  the cast Vite output, delivered by the same `app="cast"` `vite_asset` include. No
  TS-injected `<style>` strings; no Shadow DOM.
- **Tokens** (structural CSS only; colors via CSS custom properties with fallbacks):
  `--cast-player-bg` (fallback `Canvas`/`#fff`), `--cast-player-fg`
  (`CanvasText`/`#111`), `--cast-player-muted` (`#666`), `--cast-player-accent`
  (`#2d8260`), `--cast-player-progress` (`var(--cast-player-accent)`),
  `--cast-player-progress-track` (`#ccc`), `--cast-player-highlight-bg` (`#fff3b0`),
  `--cast-player-focus` (`var(--cast-player-accent)`).
- **Forced colors:** a `@media (forced-colors: active)` block sets borders/thumb to
  `currentColor`/system colors; the focus ring and current-cue marker must not rely
  on custom colors.
- **Host mapping:** cast-bootstrap5 maps these tokens to its tokens
  (`--cast-accent`, …) in SCSS; python-podcast overrides them (purple `#7c3aed` /
  `#a78bfa`) in `site-overrides.css`. Changing the mapping in cast-bootstrap5
  requires that repo's SCSS/Vite rebuild; the player code does not change per site.
- **Light/dark:** follows the host scheme (e.g. cast-bootstrap5's `data-bs-theme`)
  and `prefers-color-scheme`; correct via CSS, no JS theme detection where CSS
  suffices.

## Where It Lives, Build, and Test Commands

- **Component source:** `javascript/src/audio/` (alongside `podlove-player.ts` and
  the vitest harness `javascript/src/tests/`). New entry in `javascript/vite.config.ts`.
- **Backend:** payload builder `src/cast/player.py`; inclusion tag in a cast
  templatetags module; include `src/cast/templates/cast/audio/_custom_player.html`;
  the gate in `cast/audio/audio.html` (the StreamField audio block path); the
  fallback DRF view in `src/cast/api/views.py` + route in `src/cast/api/urls.py`;
  settings in `src/cast/appsettings.py`; checks in `src/cast/checks.py`.
- **Theme include:** cast-bootstrap5 includes the built asset via `{% vite_asset
  'src/audio/custom-player.ts' app="cast" %}` (detail template only), gated on
  `use_custom_audio_player`.
- **Commands** (existing `just` targets, `justfile:118-146`): JS tests `just
  js-test`; build `just js-build-vite` / `just js-build-all` (copies to
  `src/cast/static/cast/vite/`); Python via the repo's standard pytest invocation.
  Rebuild and verify asset/manifest freshness before backend tests that render the
  asset.

### Iteration workflow

Develop/test components against a fixture JSON in `javascript/` (vitest + an optional
Vite dev page), no Django round-trip. Once correct, wire into cast-bootstrap5
templates and validate end-to-end in python-podcast against **editable** installs of
django-cast and cast-bootstrap5 (switch `uv.sources` from git to local paths).

## Tests

### vitest (jsdom) — `just js-test`

- **Controller:** play/pause/toggle; `seek` clamps `[0, duration]` and lower-bound-
  only when duration unknown; cue boundary (inclusive start / exclusive end, gap →
  -1, overlap → last wins, exact-end, ended) and chapter boundary (last extends to
  end, before-first → -1); `timeupdate` coalesced per frame; `durationchange` fills
  null duration; `setCues` installs cues and emits `cueschange`/`cuechange`;
  listeners add/remove cleanly; `destroy` removes listeners.
- **Transport:** play/pause toggles label + state; range drag/keys call `seek`;
  spoken-time `aria-valuetext`; `m:ss`/`h:mm:ss` formatting; no `aria-live` on time;
  duration-unknown disables range + shows `--:--`; no-sources disabled state.
- **Transcript:** cues render via `textContent` (assert XSS-safety with a
  `<script>`-laden cue); cue activation seeks; current cue `aria-current` on
  `cuechange`; auto-scroll respects toggle + reduced-motion; search marks via DOM
  splitting, case-insensitive, text-only, count status, next/prev scroll+focus+wrap
  without seeking; keyboard-navigable toggle flips `tabindex`; empty renders
  nothing; `url` path shows loading then populates via `setCues`; `<cast-transcript>`
  never issues a fetch.
- **Chapters:** current chapter on `chapterchange`; activation seeks; empty renders
  nothing; `data-mode` switch.
- **Wiring:** `for=` resolves by id incl. the late `cast:player-ready` retry;
  `disconnectedCallback` unsubscribes + `destroy`s; duplicate id warns + last wins;
  two players stay independent and don't leak after one disconnects (htmx-swap sim).
- **Public API:** getters + `getShareState()` correct; `cast:timeupdate` throttled
  ~250 ms; no reference to share/download/info.

### pytest — backend

- `build_player_payload` shape + conversions (duration/title/subtitle/poster/
  sources/chapters/cues), absolute URLs via `request`, chapter time-string parsing,
  malformed-row skipping + logging. Cue `end` normalization: missing/unparseable/
  non-finite `end` and `end <= start` are synthesized from the next cue with a
  strictly greater `start` (and the last/no-later cue from `duration` or
  `start + 5`); **including a duplicate/same-start-cue case** that asserts the
  synthesized `end` is still `> start`. Every emitted cue has finite `end > start`,
  the synthesized-`end` count is logged, and cues without a finite `start` or with
  empty `text` are skipped + counted.
- **Sanitization parity:** non-public speakers removed/mapped identically to the
  serializer in both inline and fallback paths; assert raw `podlove_data` is never
  emitted.
- Size cap: over the cap, cues omitted, `transcript.url` set, log emitted.
- Fallback endpoint: public read; sanitized normalized `{cues}`; 404 on
  missing/non-live/mismatched `post_id`; never serves the raw Podlove file.
- Rollout gating: `custom` renders the custom markup + `json_script` on the detail
  path (StreamField audio blocks) and sets `use_custom_audio_player`;
  `podlove` (default) unchanged; list cards in custom mode render no player and no
  inline transcript; feeds unchanged.
- Settings/checks: defaults present; `CAST_AUDIO_PLAYER` value check and byte-cap
  type check fire on bad input.

### Accessibility

Assert ARIA/keyboard contracts directly in vitest (button names, labels, valid ARIA,
no positive `tabindex`, `aria-current` usage, no `aria-live` on transcript/time).
Automated axe is **not** added as a dependency in v1; a manual Lighthouse/axe pass on
python-podcast is part of the final slice.

## Lighthouse / Performance Requirements

- Single self-contained bundle, no framework baseline; document the JS budget;
  assert bundle presence/size in CI if feasible.
- No render-blocking transcript fetch in the default (inline) path.
- No cumulative layout shift: reserve control dimensions; collapse absent chapter/
  transcript regions; reserve transcript height while a `url` fallback loads.
- Audio uses `preload="metadata"` (decided) so the page does not eagerly download
  audio.
- `type="module"` / deferred component script; do not block first paint.
- Throttle per-`timeupdate` DOM work via `requestAnimationFrame`; throttle the public
  event to 250 ms.

## List and Overview Pages

In v1 the custom player renders **only on the episode detail path** (`render_detail=
True`). List cards (`render_detail=False`) render no audio player, no inline
transcript, no chapters, and load no player JS. The component supports
multiple instances per page via the id registry (needed for tests and the future
persistent player); the v1 server render path emits one custom player per rendered
`audio` block (typically one on an episode detail page, but more if the body
contains several audio blocks). A list-card "play" affordance is deferred to the
persistent-player follow-up.

## Persistent Player (future, out of scope here)

Recorded so the component is built persistence-ready, not implemented now:

- django-cast already ships htmx, wraps content in `#paging-area`, and runs
  View-Transition swaps for pagination (`src/cast/templates/cast/plain/base.html`,
  `pagination.html`, `src/cast/static/cast/css/plain/cast.css`,
  `src/cast/static/cast/js/paging-view-transition-fix.js`).
- A future spec can promote the single controller to one persistent player by
  relocating `<cast-audio-player>` to a `<body>`-level region **outside**
  `#paging-area`, extending boosting from pagination-only to link navigation
  (`hx-boost`), and having per-episode "play" buttons drive the one global player by
  `for=` id. Cross-document View Transitions, Service/Shared Workers, and
  prerendering cannot keep audio playing; only avoiding the full navigation works.
- Implication: keep the controller UI-agnostic, key views by id, register/cleanup
  precisely, and keep the public contract stable so promotion needs no rewrite.

## Implementation Slices

One design document; implementation proceeds as independently shippable slices (each
with its own tests, behind `CAST_AUDIO_PLAYER="custom"` until the detail path is
complete):

1. **Backend payload builder + sanitization parity** (`src/cast/player.py`) with
   pytest, reusing the public speaker-sanitization helper. Settings + checks
   (`appsettings.py`, `checks.py`). No frontend.
2. **Transport-only component + inline JSON + rollout gating**: `custom-player.ts`
   (controller + `<cast-audio-player>` transport UI), the inclusion tag + JSON
   contract, the `audio.html` template gate (custom on `render_detail=True`, no
   player on list cards), and the default `_custom_player.html` element placement.
   vitest + pytest.
3. **Chapters view** (`<cast-chapters>`).
4. **Transcript render / click-to-seek / highlight / auto-scroll**
   (`<cast-transcript>`), inline path only.
5. **Transcript search + keyboard-navigable toggle**.
6. **Long-transcript sanitized fallback**: cap setting, the
   `cast:api:audio_player_transcript` endpoint with its public-validation contract,
   and `setCues` wiring.
7. **Theme tokens in cast-bootstrap5 + python-podcast polish + Lighthouse/axe audit**.

## Sibling Repo Impact

- `../cast-bootstrap5`: maps the player CSS tokens in SCSS; includes the
  django-cast-built asset via `app="cast"` (detail template), gated on
  `use_custom_audio_player`; gates Podlove preconnect on `use_podlove_player`;
  requires its SCSS/Vite rebuild when token mapping changes. No model/API change, no
  duplicate JS build.
- `../python-podcast`: overrides tokens for its purple palette; end-to-end validation
  site via editable installs; final Lighthouse/axe pass.
- `../django-chat`: not required; its share/embed `<dialog>` pattern is a reference
  only if independent share UI is later built. Share is out of scope here.
- `../cast-vue`: unaffected.

## Documentation and Release Notes

This change adds a user-facing player option, two settings, a template/include, a
theming token surface, and a public endpoint, so docs and release notes are part of
the work (per `AGENTS.md` conventions):

- Update `docs/media/audio-and-transcripts.rst` (the existing audio/transcript page)
  to document the custom player, `CAST_AUDIO_PLAYER`,
  `CAST_PLAYER_INLINE_TRANSCRIPT_MAX_BYTES`, the theming token surface, and the
  `cast:api:audio_player_transcript` endpoint. Cross-reference settings/reference
  docs as appropriate.
- Add a release note for the version shipping each slice (at minimum the detail-page
  custom player).
- Document the theming contract for cast-bootstrap5/consumer sites.

## Decisions (previously open questions)

- `preload="metadata"` is the default (revisit only if the slice-7 audit shows a
  better trade-off).
- `CAST_PLAYER_INLINE_TRANSCRIPT_MAX_BYTES` default `150_000`, measured as raw bytes
  of the JSON-serialized cues array.
- Element names: `cast-audio-player`, `cast-transcript`, `cast-chapters`. Event
  namespace: `cast:`. Verify no collision when registering in slice 2.
- Chapter `href`/`image` omitted in v1 (seek-only chapters); link-out is a later
  enhancement.
- No-JS / no-component transcript fallback already exists: the public transcript
  pages (`src/cast/templates/cast/plain/transcript.html`,
  `src/cast/templates/cast/bootstrap4/transcript.html`) and the transcript file
  endpoints (`src/cast/urls.py`). The custom player does not add a separate no-JS
  path.

## Success Criteria

- With `CAST_AUDIO_PLAYER="custom"`, the detail path renders the custom player (no
  iframe, no facade) at the StreamField `audio` block render path; with the default
  `"podlove"` nothing changes; list cards render no player and inline no transcript;
  feeds unchanged; the cast-vue SPA path is untouched.
- The player renders immediately from inlined JSON with no transcript fetch for
  normal-length episodes; over-cap transcripts fall back to a single fetch from the
  sanitized endpoint; non-public speaker labels never leak in either path; raw
  `podlove_data` is never emitted publicly.
- Transport (play/pause, draggable seek, time, duration-unknown handling), transcript
  (search, speakers, highlight, auto-scroll, click-to-seek, drag-to-jump, XSS-safe
  rendering), and chapters (current marker, click-to-seek) all work and stay in sync
  via the shared controller.
- The transcript element renders correctly when placed away from the transport bar.
- Show notes/info, download, and share remain fully independent; the player only
  exposes a read-only position API.
- Zero runtime dependencies; themed entirely via CSS custom properties; correct in
  light, dark, and forced-colors modes.
- vitest covers controller, transport, transcript, chapters, wiring, public API;
  pytest covers the payload builder, sanitization parity, size-cap fallback,
  endpoint validation, rollout gating, and settings/checks. `just js-test` and the
  pytest suite pass; assets build via `just js-build-vite`.
- Lighthouse performance and accessibility audits pass cleanly (no accessibility
  failures; small JS payload; no CLS; no eager audio download).
- The audio controller is UI-agnostic and id-addressable, so a later persistent
  player needs no component rewrite.
- `docs/media/audio-and-transcripts.rst` and release notes describe the new
  settings, template/include, theming tokens, and endpoint.
