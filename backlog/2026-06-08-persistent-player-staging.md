# Persistent Audio Player on python-podcast Staging

## Status

**Implemented as a python-podcast-local staging proof (2026-06-08).** The proof
keeps one live `<cast-audio-player>` alive across enhanced navigation on the
python-podcast `pp` theme. django-cast and cast-bootstrap5 are **unchanged** —
the proof composes only the existing public custom-player HTML contract
(`json_script` payload + `<cast-audio-player data-payload>` + `<cast-transcript>`
/`<cast-chapters>`), so it needed no django-cast internals or new django-cast
APIs. See "Implementation Log" at the bottom for what was built, what was proven,
and what a generic rollout would require.

The text below is the original PRD / implementation spec. It is deliberately
scoped to a staging proof on `python-podcast.staging.django-cast.com`; it is not
a production rollout plan.

## Goal

On python-podcast staging, a reader can start an episode in the custom player,
navigate between internal public pages, and the same audio continues playing
without a full document reload stopping playback.

This should prove the larger persistent-player direction with real
python-podcast templates, hosting, audio files, and browser behavior before
turning it into a generic django-cast/theme feature.

## Current State

- django-cast already ships the custom player behind `CAST_AUDIO_PLAYER =
  "custom"` and python-podcast staging serves it.
- The current `<cast-audio-player>` is page-local. Its `disconnectedCallback`
  unregisters and destroys the controller, which is correct for the shipped
  detail-page component but means normal swaps or full navigations stop playback.
- List pagination already uses htmx swaps around `#paging-area`, but episode
  detail/list/about navigation is still normal page navigation.
- The custom player exposes a read-only API and honors `?t=`. Transcript loading
  is lazy and cached with `Cache-Control`/`ETag`, so this slice does not need a
  second transcript-cache mechanism.
- Existing custom-player output is rendered by the StreamField audio block on
  detail pages only; list cards intentionally render no player in custom mode.
- The python-podcast `pp` theme already wraps its main/footer region in
  `#paging-area` in `python_podcast/templates/cast/pp/base.html`. That is the
  primary staging proof boundary. The Bootstrap 5 override also has page-level
  htmx handling around `#paging-area` on list pages, but it is not the first proof
  target unless the active staging theme requires it.

## Non-goals

- Do not enable this on production.
- Do not replace Podlove on production sites.
- Do not make all themes persistent in this slice.
- Do not build a queue, playlist, speed controls, volume controls, or a native
  media-session integration.
- Do not turn django-cast into a full SPA. The proof should use progressive
  enhancement and keep normal links as the fallback.
- Do not change podcast feeds, public transcript file endpoints, or the
  cast-vue `podlove_players` API.

## Proposed Shape

### Stage behind an explicit flag

Add a staging-only opt-in setting in python-podcast, for example
`PYTHON_PODCAST_PERSISTENT_AUDIO_PLAYER = True`, and keep it disabled outside
staging. If the implementation needs reusable django-cast support, gate that
support with a neutral django-cast setting or template flag, but the public test
surface remains python-podcast staging.

### Keep one player outside `#paging-area`

For the first staging proof, use the existing `cast/pp/base.html` `#paging-area`
as the htmx-swapped page content. Render a persistent player region as a sibling
of `#paging-area` in that base template. This region owns the single live
`<cast-audio-player>` / `AudioController` instance. Navigating page content must
not disconnect that element.

Because `#paging-area` wraps the `pp` theme main/footer content, the footer may
re-render with normal page content during enhanced navigation. The persistent
player region sits outside that wrapper and must not re-render during those
swaps.

The first proof may place this region near the bottom of the viewport as a
compact now-playing bar, but the UI can stay intentionally plain. The goal is to
prove continuous playback and lifecycle boundaries, not final visual polish.

### Let detail pages publish payloads, not live players

When the persistent-player flag is enabled, episode detail pages do **not** render
an in-body `<cast-audio-player>`. They publish the existing sanitized custom
player payload with `json_script` and render an inert "play this episode" action
in the original audio-block location. That action points at the payload id and is
wired by the persistent manager.

The persistent manager should be able to discover the current page's episode
payload after an htmx navigation and update the persistent player only when the
reader explicitly starts that episode. Merely navigating to an episode page
should not interrupt already-playing audio. With the flag disabled, the shipped
page-local custom player continues to render unchanged.

### Use htmx for internal public navigation

On staging, progressively enhance internal public links with htmx navigation.
For the `pp` theme proof, boosted links target `#paging-area`, select
`#paging-area` from the response, push the URL, and keep the persistent player
region outside the target. Preserve normal navigation for:

- external links;
- feed/download/audio-file links;
- admin/account/auth links;
- forms, search, filters, and comment submission until explicitly verified;
- pages whose response does not contain the selected `#paging-area` target;
- links with `target`, `download`, non-HTTP schemes, or hash-only behavior.

Full reloads may stop playback; same-document enhanced navigation should not.

### Title, focus, scroll, and history rule

For the staging proof, keep this deterministic rather than trying to emulate a
full browser navigation:

- Every enhanced navigation updates `document.title` from the response's
  `<title>` before the swap settles, or uses htmx's title handling when that is
  already sufficient.
- After each enhanced navigation and htmx history restore, focus moves to the
  first visible `h1` inside `#paging-area`; if there is no `h1`, focus moves to
  `#paging-area` after temporarily making it focusable with `tabindex="-1"`.
- Enhanced navigation resets `window.scrollTo(0, 0)` after settle. Hash-only
  links are excluded from enhancement, so hash scrolling stays browser-native.
- Back/forward uses htmx history restoration for content and URL, then applies
  the same title/focus/top-scroll rule. The proof does not require preserving the
  previous scroll offset.

This rule is intentionally plain, accessible, and testable. If it feels too
rough in staging, polish it after the continuous-playback lifecycle is proven.

### Define episode switching

For the staging proof:

- Starting playback on episode A loads episode A into the persistent player.
- Navigating away keeps episode A playing.
- Navigating to episode B does not replace episode A automatically.
- Pressing episode B's play action replaces the persistent player source with
  episode B and starts playback from the beginning, unless the existing
  `?t=<seconds>` receiver behavior is deliberately used.

## Acceptance Criteria

- `python-podcast.staging.django-cast.com` can be deployed with the persistent
  player flag enabled while production remains unchanged.
- Starting playback on a staging episode and navigating to at least the podcast
  index, another episode page, and `/about/` keeps the same audio playing and
  advancing. If `/about/` does not render through a response containing
  `#paging-area`, first add or select the staging-shell target before enhancing
  that link.
- Navigating to another episode does not interrupt the current audio until the
  reader explicitly starts that other episode.
- Starting another episode replaces the persistent player cleanly: one audio
  element is active, the previous controller is destroyed or retired, and no
  duplicate global keyboard handlers/listeners remain.
- Transcript and chapter views for the active player continue to work after
  navigation. If the transcript has already loaded, it is not rebuilt by a page
  render; repeat endpoint requests are served from browser cache or return 304.
- Back/forward navigation is verified with Playwright: after navigating episode
  detail -> index -> another public page -> back, the URL and document title match
  the expected page, the primary heading text matches the visible page, focus is
  on the first visible `h1` inside `#paging-area` or on `#paging-area`, scroll is
  at the top according to the documented rule above, and the persistent audio
  current time is still advancing.
- Non-enhanced links and excluded flows still fall back to normal navigation.
- Playwright verification covers the continuous-playback path on staging or a
  staging-equivalent local server. The test must set a token on `window`, start
  playback by clicking the visible player control, store the active `<audio>`
  object, navigate with an enhanced internal link, assert the token remains (same
  document), assert the active `<audio>` object is still the current player audio,
  and assert `currentTime` advances while `paused === false`.
- Listener/controller cleanup is covered by a frontend unit or Playwright test:
  after at least three enhanced navigations and one explicit episode switch,
  there is exactly one persistent player host, one active `<audio>` element, no
  duplicate controller-id warnings, and the manager's test-visible diagnostics
  report a stable listener disposer count.
- Axe or Lighthouse accessibility checks on the staging proof show no new
  player/navigation violations before considering production work. The baseline
  is the current custom-player staging axe result recorded in the follow-up note:
  0 violations on `python-podcast.staging.django-cast.com`.
- Documentation/backlog notes record what was proven, what remains staging-only,
  and what would be required for a generic django-cast rollout.

## Implementation Slices

1. **Template boundary.** In `python_podcast/templates/cast/pp/base.html`, add a
   staging-flagged persistent player slot outside the existing `#paging-area`.
   Use `#paging-area` as the initial htmx target/select boundary for `pp` theme
   public navigation. Keep responses without `#paging-area` on normal navigation.
   Implement the title/focus/top-scroll rule in this slice or in the navigation
   slice before Playwright verification starts.
2. **Persistent manager.** Add the smallest frontend code needed to keep one
   player alive outside swapped content, discover episode payloads in newly loaded
   content, render/load the single persistent `<cast-audio-player>` from the
   selected payload, and switch episodes only when the reader clicks a page's
   inert "play this episode" action. For tests, expose manager
   diagnostics in a non-public way (for example an exported test helper or a
   staging-only `window.__castPersistentAudioDebug`) so listener disposer count,
   active player id, and switch count can be asserted without guessing from DOM
   side effects.
3. **Staging navigation.** Enable htmx navigation for allowed internal public
   links on python-podcast staging only. Keep full-page fallback intact.
4. **Verification.** Add/run Playwright checks for continuous playback, episode
   switching, back/forward, excluded links, and accessibility. Capture the staging
   URLs and results in this note or a linked handoff.
5. **Deploy hygiene.** Pin python-podcast staging dependency refs to branches or
   commits containing the proof (`django-cast`, and `cast-bootstrap5` only if it
   changes), update `uv.lock`, and verify production settings/deploy vars do not
   enable the persistent-player flag.
6. **Decision.** Decide whether to generalize into django-cast/cast-bootstrap5,
   keep it python-podcast-specific, or abandon the approach based on the staging
   evidence.

## Decisions for the Staging Proof

- The persistent manager lives in python-podcast for the proof. Move reusable
  pieces into django-cast only if the implementation would otherwise duplicate
  existing player internals or require fragile private imports.
- The persistent region owns the full active-player surface: transport plus
  transcript and chapters panels. Panels may start collapsed after navigation,
  but the active player's transcript/chapter functionality must keep working.
- Persistent mode never has both an in-body `<cast-audio-player>` and the
  persistent `<cast-audio-player>` for the same episode. The in-body audio block
  becomes a payload publisher plus play action while the persistent flag is on.
- Use a compact fixed bottom player region for the proof. Keeping the player in
  the original episode-body position while physically outside the swapped content
  is deferred until after the lifecycle is proven.

## Open Questions

- If the python-podcast-only manager proves successful, what is the smallest
  generic django-cast/cast-bootstrap5 API that would let other server-rendered
  themes adopt it without copying site-specific navigation rules?

## Sibling Repo Impact

- `../python-podcast`: primary implementation and staging deploy target.
  Staging currently resolves django-cast/cast-bootstrap5 through
  `[tool.uv.sources]`; the deploy branch/commit refs and `uv.lock` must be part
  of the staging proof, and production settings must keep the flag disabled.
- `../cast-bootstrap5`: inspect if the proof reuses Bootstrap 5 template
  contracts or assets, but do not merge generic changes unless needed for the
  staging proof.
- `../django-cast`: may need small reusable player-manager APIs or template tags.
- `../django-chat`: no change in this slice.
- `../cast-vue`: unaffected.

## Update (2026-06-09): bootstrap5 + per-episode overview play

Extended the proof from `pp` to the **bootstrap5** theme (python-podcast's
default) and made bootstrap5 the staging default, so the persistent player is the
default visit experience at `python-podcast.staging.django-cast.com`. Also added
**a play action per episode on the overview/list cards** (start any episode from
the index; it loads into the persistent player and keeps playing as you
navigate).

- The manager's content swap target is now theme-declared via
  `data-cast-swap-target` on the region (`pp` → `paging-area`, `bootstrap5` →
  `main-content`); the manager reads it at init.
- bootstrap5 persistent region lives in `cast/bootstrap5/base.html`
  (`{% block modal %}`, outside `#main-content`); the list template overrides
  `before_main`, so the region can't live there. The bootstrap5 index identity
  (`h1` + description) is rendered inside `#main-content` in persistent mode so
  enhanced navigation swaps it (no stale hero).
- Episode detail AND overview cards publish via `cast/<theme>/audio.html` +
  the `cast_player_payload` tag + the shared `cast/_persistent_play_action.html`.
  The tag re-fetches the concrete page for lightweight repository (list) posts.
- Enhanced navigation now also excludes any `#fragment` link; `popstate` only
  acts on manager-created entries (no contention with htmx pagination history).
- Real-staging Playwright passes on the default bootstrap5 theme (continuous
  playback across index/other-episode/`/about/`/back, same audio object, clean
  switch, title updates, scroll-top + focus, axe 0, 0 console errors). Local e2e
  is parametrized over **pp + bootstrap5**. Staging theme defaults (site + `show`
  blog → `bootstrap5`) are reversible staging-DB settings; production unaffected.

## Update (2026-06-11): navigation reservation + now-playing cards + card morph

Deployed to staging and verified there (Playwright `tests/e2e/staging_goal_check.py`
in python-podcast, all checks pass; Pi judged the goal achieved from the JSON
results + screenshots; the baseline `staging_persistent_player.py` suite still
passes with axe 0 / console 0):

- **The dock no longer blocks navigation.** The fixed 8.5rem body padding could
  not cover the expanded transcript/chapters sheet (~42vh), which occluded the
  bottom pagination on list pages. The manager now tracks the dock's real
  height with a ResizeObserver into `--cast-dock-height`; `body.cast-dock-open`
  reserves `padding-bottom`/`scroll-padding-bottom` from it, so pagination and
  footer always scroll clear of the dock. Moving the dock in-flow (between list
  and pagination) was rejected — inside the swap boundary it cannot persist;
  top placement stays the rejected alternative from the design spec.
- **Play cards mirror global playback state.** Cards were redesigned as one
  cohesive surface (poster, circular accent control, label + duration,
  full-card hit area) and the manager now writes `data-cast-state=
  "playing"|"paused"` onto the active episode's card: pause glyph, equalizer
  badge over the poster, live elapsed/total readout, accent border. Clicking
  the active card toggles pause/resume on the single live controller instead
  of restarting. State re-applies after enhanced navigation and htmx
  pagination swaps; cards stay projections (no controller, no second audio).
- **The pressed card morphs into the dock.** The View Transition now names the
  whole card (`cast-vt-card`, dock inner as target on first open) with the
  poster as a nested pair, so the card visibly becomes the player; the rise
  entrance remains the no-card fallback and the reduced-motion/no-VT floor is
  unchanged.

## Update (2026-06-11, round 2): transcript visibility fix + dock minimize

The "transcript opens as a dead empty panel" report on staging had a data root
cause: **63 of 67 staging transcripts referenced S3 objects that did not
exist** (stale `pp_*` file names from an old production snapshot; production
had since renamed the files to `audio-<pk>.*`). The endpoint returned
`{"cues": []}` with HTTP 200 and the player rendered an opened panel as a bare
toolbar with no message. Fixed on three layers:

- **django-cast (`26480124`, pushed to develop):** a transcript that lazily
  resolves to zero cues now shows "No transcript available for this episode."
  and hides the search/follow toolbar; a failed fetch hides the tools the same
  way and a successful retry restores them. Covered by vitest cases and a
  python-podcast e2e test with a real zero-cue transcript fixture. Release
  note added to 0.2.59.
- **Staging data repair (DB + bucket, no code):** all 189 missing objects
  (podlove/vtt/dote × 63) were exported from production storage and re-saved
  into staging via `FieldFile.save`, so references and objects are consistent
  again; 0 dangling references remain and the originally reported episode
  (DjangoCon Tag 1, audio 78) serves 964 cues. A future staging DB refresh
  from a production snapshot must re-run this repair (or copy the media
  alongside the DB).
- **python-podcast dock:** new minimize/expand control — a one-row strip
  (poster · title · play · elapsed · expand · close) that hides
  subtitle/seek/share/shortcuts/panels via CSS only, preserving panel open
  state across a minimize round-trip and following the dynamic space
  reservation automatically; equalizer badge timing varied per bar.

Verified on staging (17/17 goal checks incl. Tag-1 cues, minimize/restore,
pagination-above-dock; baseline suite green with axe 0); Pi reviewed both
diffs (CLEAN) and judged the goal ACHIEVED from the JSON results +
screenshots. Local e2e also re-aligned the page-local scroll assertion with
the follow-along look-ahead margins.

## Implementation Log (2026-06-08)

### What was built (all in `../python-podcast`, `pp` theme only)

- **Flag.** `PYTHON_PODCAST_PERSISTENT_AUDIO_PLAYER` (default **False** in
  `config/settings/base.py`). **True** in `staging.py` + `e2e.py` + `local.py`;
  **pinned False** in `production.py` so no env var can enable it in production.
  Exposed to templates via `python_podcast.pp.context_processors.persistent_audio_player`
  and the `{% pp_persistent_player_enabled %}` tag (inclusion-tag contexts do not
  carry context processors).
- **Persistent region (outside `#paging-area`).** `cast/pp/base.html` renders an
  empty `<div id="cast-persistent-player" hidden>` as a sibling of `#paging-area`
  when the flag is on, and loads the django-cast custom-player bundle **globally**
  (so the web components are defined on every page, not just episode pages) plus
  the manager script. `#paging-area` (which wraps the `pp` main+footer) stays the
  swap boundary; the region is never re-rendered during swaps.
- **Publish-only episode pages, scoped to `pp`.** A `pp`-theme-only audio block
  override `cast/pp/audio.html` (resolved by django-cast's
  `get_block_template` → `cast/<theme>/audio.html`) publishes the sanitized
  payload (`json_script`) + an inert "play this episode" action (the
  `pp_publish_player` tag, reusing `cast.player.build_player_payload`) instead of
  an in-body live player — **only** when the flag is on, the custom player is
  active, and it is a detail render. Every other case (podlove mode, list cards,
  feeds, flag off, **any non-`pp` theme**) falls through to the upstream audio
  block unchanged. (Scoping to `pp` is essential: other themes have no persistent
  region, so a global override would render a dead button — caught in review.)
- **Persistent manager + enhanced navigation** (`python_podcast/static/js/persistent-player.js`,
  dependency-free vanilla JS): keeps one live player alive outside `#paging-area`;
  discovers the current page's published payload and wires its play action;
  switches episodes only on an explicit play click (tears the old player down →
  one host, one `<audio>`, no duplicate-controller-id warnings); progressively
  enhances internal public links via `fetch` + `#paging-area` swap with the
  documented exclusions (external, `download`, non-HTTP, hash-only, feed/media,
  admin/account/api/comments, forms, existing htmx controls); updates
  `document.title` from the response, scrolls to top, moves focus to the first
  visible `h1` in `#paging-area` (else `#paging-area` with `tabindex="-1"`); and
  handles back/forward by re-fetching content (the persistent region is never
  touched, so audio keeps advancing). Test diagnostics live on
  `window.__castPersistentAudioDebug` (active payload/audio id, switch count,
  host/audio counts, listener-disposer count, `getActiveAudio()`).

### Staging access

The persistent proof is the **`pp` theme** experience, and on staging `pp` is
now the **default theme**, so a normal visit to
`python-podcast.staging.django-cast.com` shows the persistent player keeping
audio playing across navigation (no theme switch needed). This was set via two
**staging-DB settings** (not code, reversible): the site-level
`TemplateBaseDirectory` and the `show` blog's `template_base_dir` were both set
to `pp` (`manage.py shell`). Other themes remain selectable via the theme
switcher / `?theme=bootstrap5`. Production is a separate site/DB and is
unaffected (Podlove, persistent flag pinned `False`).

### What was proven

- **Local (staging-equivalent), `tests/e2e/test_persistent_player.py`, 2 passing:**
  episode pages are publish-only (no in-body `<cast-audio-player>`, host count 0
  until an explicit start); starting episode A through the visible action yields
  exactly one host/`<audio>`; enhanced navigation to the podcast index and to
  episode B's page keeps the **same** `<audio>` object active, the document token
  intact (same-document), and `currentTime` advancing with `paused === false`;
  starting episode B replaces cleanly (switch count +1, one host, one `<audio>`,
  no duplicate-id warnings); the transcript + chapter panels work on the active
  player and are **not** refetched/rebuilt by navigation; back/forward keeps audio
  advancing with scroll-to-top + the focus rule; zero console errors. Plus
  `tests/test_persistent_player_config.py` (flag plumbing) and a fall-back check
  for excluded (feed) links.
- **Real staging (`tests/e2e/staging_persistent_player.py` against
  `python-podcast.staging.django-cast.com`, 2026-06-08): all checks PASS.**
  Selecting the `pp` theme, the episode page is publish-only (no in-body
  `<cast-audio-player>`); starting `/show/data-science/` through the visible
  action yields one host/`<audio>`; enhanced navigation to the podcast index, to
  another episode (`/show/platonismus-und-python-data-class-builders/`), and to
  `/about/` keeps the **same** `<audio>` object active in the **same document**
  (the `window` token survives) with `currentTime` advancing and
  `paused === false` at every hop; an explicit play on the other episode switches
  cleanly (switch count +1, one host, one `<audio>`); back keeps audio advancing
  with scroll-at-top; `document.title` updates on enhanced navigation
  (`Data Science` → `Python Podcast`); the index's own `<h1>` is present inside
  `#paging-area` after the swap (no stale chrome); and **axe-core reports 0
  violations** with **0 console errors**. This matches the axe-0 custom-player
  staging baseline — the persistent player/navigation adds no new violations.
  (Bringing `/about/` into the proof required the pp-shell fixes below.)

  Test note: the e2e browsers launch with `--disable-audio-output` (a null audio
  sink) so the media playback clock advances even when the host's real audio
  device is unavailable/wedged; without it `currentTime` can stall at ~0 with
  `paused === false`. This is a test-environment flag only.

### pp staging-shell fixes (needed for the proof on `pp`)

Staging defaults to bootstrap5 (axe-0, complete shell); the `pp` theme had
pre-existing shell gaps that surfaced once it became the proof theme and that the
spec anticipated ("add or select the staging-shell target before enhancing that
link"). Fixed in python-podcast's own `pp` templates:

- `post.html` `{% block title %}` now wraps the title in `<title>` (it previously
  emitted bare text — which broke both `document-title` a11y **and** the enhanced
  navigation's title update, since the manager reads the response `<title>`).
- One `<main>` landmark per page (in `base.html`, wrapping both the `main` and
  `content` blocks) and an `<h1>` for the detail title (`post_body.html`), fixing
  `landmark-one-main`, `page-has-heading-one`, and `region`.
- `blog_list_of_posts.html` headings `h4` → `h2` (heading-order), and the two
  pagination `<nav>`s get distinct labels (`landmark-unique`).
- The persistent region is a labelled `role="region"` landmark.
- Flat `TemplateView` pages (`/about/`, `/dsgvo/`, `/impressum/`) now extend the
  **session-aware** theme base (`cast_session_base_template`) instead of the
  site-default `cast_base_template`, so under the `pp` proof they render inside
  the `pp` `#paging-area` shell with the persistent region present — which is why
  enhanced navigation to `/about/` keeps audio playing. (Default/bootstrap5
  rendering is unchanged: with no session theme the session-aware base resolves
  to the site default.)

### What remains staging-only / generic-rollout requirements

- The proof is `pp`-theme-specific and python-podcast-local. A generic
  django-cast/cast-bootstrap5 rollout would need: a reusable persistent-region
  template tag/partial; a documented theme contract for the swap boundary
  (`#paging-area` here) and where the persistent region must sit relative to it; a
  packaged manager (built into the cast Vite bundle rather than a per-site static
  JS file) with a small public config for the site-specific navigation
  exclusions; and per-theme audio-block publish variants
  (`cast/<theme>/audio.html`). The open question in this note — the smallest
  generic API — is unchanged.
- Back/forward intentionally **re-fetches** `#paging-area` rather than using
  htmx's history snapshot, to guarantee the persistent region is never clobbered.
  `popstate` only acts on entries the manager created (`{castNav: true}`), so it
  never competes with htmx's own history handling (e.g. list pagination). That is
  fine for the proof (the spec does not require restoring scroll offset).
- Enhanced navigation excludes **any** link carrying a `#` fragment (same- or
  cross-page, e.g. `/about/#team`), so native fragment scrolling is preserved
  rather than scrolling to top.

### Review / deploy notes

- Reviewed with Pi (`gpt-5.5`) over multiple rounds; all real findings were
  fixed (theme-scoped publish-only override, `htmx:afterSettle` re-wiring,
  e2e tests excluded from the default `pytest` run, podlove-mode asset gating,
  `popstate` scoped to manager-owned entries, fragment-link exclusion).
- **Accepted as out of scope for this staging proof:** the python-podcast
  `[tool.uv.sources]` refs (`cast-bootstrap5` → `feat/custom-player-rev4`,
  `django-cast` → `develop`) are shared by staging + production installs. They
  predate this slice (prior custom-player work) and production behaviour is
  unchanged (Podlove, `CAST_AUDIO_PLAYER != "custom"`, persistent flag pinned
  `False`). A production rollout must still revert these to release/main refs —
  tracked in `2026-06-03-custom-audio-player-follow-ups.md`.

### Tooling note

`just js-bundles` (django-cast) is implemented tooling (`scripts/show_bundle_sizes.py`),
not active backlog.
