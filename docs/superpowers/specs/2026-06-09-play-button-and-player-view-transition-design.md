# Play Button & Player View-Transition Design

**Date:** 2026-06-09
**Status:** Design proposal (for Pi review before any implementation)
**Scope:** The custom audio player's *play affordance* and the *visual hand-off*
from an inline, in-episode play surface to a single persistent/global player.

## Problem

The custom player (`CAST_AUDIO_PLAYER = "custom"`, web components in
`javascript/src/audio/`) renders a pill transport inline in the episode body.
The persistent-player staging proof (`backlog/2026-06-08-persistent-player-staging.md`)
proved that one live `<cast-audio-player>` can survive enhanced navigation if it
lives in a docked region outside the swapped content. In that proof:

- The episode body renders an **inert "play this episode" action** instead of an
  in-body player (publish-only).
- A docked region at the bottom owns the single live player.
- On play, the docked region simply has its `hidden` attribute removed — **it
  pops into existence with no spatial or motion link to the button the reader
  just clicked.**

Two weaknesses follow:

1. **The play affordance is thin.** It is a bare button. It does not read as the
   primary action of the page, gives no buffering feedback, and does not reflect
   whether *this* episode is the one currently playing in the dock.
2. **The hand-off is a cut, not a move.** The reader clicks at position A (in the
   article) and a bar appears at position B (screen edge) with nothing connecting
   them. The relationship "what I pressed is now playing down there" must be
   re-inferred each time.

The shipped page-local mode (no dock) is fine and stays the default. This design
addresses **persistent mode** and is written so the persistent player can be
generalised out of the python-podcast proof into django-cast core later. Every
play-button improvement below is scoped to the persistent-mode card and dock
surfaces; page-local mode is deliberately left unchanged by this design (see the
note under "Play-button polish" for why page-local adoption is a separate,
optional follow-up rather than part of this scope).

## Goal

- A play affordance that clearly reads as the page's primary action, gives
  buffering feedback, and reflects the global playback state for its episode.
- A motion-continuous hand-off: pressing play **moves** the play surface into the
  dock (poster + play glyph fly to the bar), so the dock reads as "the thing I
  pressed, now parked at the edge". Reversible on dismiss.
- Progressive enhancement: full functionality and correctness with no animation
  on browsers without the View Transitions API and under `prefers-reduced-motion`.
- At most one live controller/`<audio>` (one while a player is docked, zero once
  the dock is dismissed) — preserving the proof's one-host invariant. The inline
  surface is a *projection* of the dock controller, never a second controller.

## Non-goals

- No change to page-local (non-persistent) custom mode, Podlove mode, feeds, or
  the transcript/chapter endpoints.
- No queue, playlist, speed, or volume controls (out of scope, as in the proof).
- Not a full SPA; enhanced navigation and its fallbacks are unchanged.
- This document does **not** itself generalise the proof into core; it specifies
  the play-button and transition design that such a generalisation would adopt.

---

## Decision 1 — Dock position: **bottom**

Three options considered:

| Option | For | Against |
| --- | --- | --- |
| **Bottom dock (recommended)** | Universal podcast convention (Spotify, Apple Podcasts, Pocket Casts, Overcast); thumb-reachable on mobile; clear of top site nav/sticky headers; downward dismissal reads naturally. | Can overlap a mobile sticky footer/cookie bar; must reserve `scroll-padding-bottom` so it never covers content. |
| Top dock | Always visible on desktop without scrolling; can merge with a media-aware header. | Collides with sticky site headers and theme nav; unconventional for audio; "fly up off the top" dismissal is awkward. |
| Inline-only, sticky-in-place | No second region; simplest. | Defeats the persistent-player goal — playback can't survive the content swap if the player lives inside swapped content. |

**Recommendation: bottom dock**, matching the proof. Top dock is recorded as the
rejected alternative; the design keeps `--cast-dock-edge` so a host could flip it,
but bottom is the supported default. The dock reserves layout space via
`scroll-padding-bottom` and a spacer so it never occludes the last paragraph or
the footer.

## Decision 2 — Transition mechanism: **View Transitions API, with manual-free fallback**

| Option | For | Against |
| --- | --- | --- |
| **View Transitions API (recommended)** | Browser does the FLIP; declarative `view-transition-name` pairs the inline poster/glyph with the dock's; same-document API is shipped in Chromium 111+ and Safari 18+, with Firefox following later (treat Firefox as the no-animation fallback until it ships); trivial, correct fallback (`if (!document.startViewTransition) { update(); return; }`). | Name-uniqueness must be managed (a name may exist on only one rendered element per snapshot); needs care across enhanced navigation. |
| Manual FLIP (measure rects, animate a clone with WAAPI) | Works everywhere; full control. | We hand-write the measure/clone/cleanup that the platform already does; more code to keep correct across reflow, theming, and reduced-motion. |
| No animation (today's behaviour) | Zero risk. | This is the status quo the goal asks us to improve. Kept as the fallback path, not the primary. |

**Recommendation: View Transitions API** as the enhancement, falling straight
through to the no-animation DOM update when unsupported or when the user prefers
reduced motion. No manual FLIP — the fallback is simply "do the same DOM change
without wrapping it in a transition", which is exactly the proof's current
behaviour, so the floor never regresses.

### Name-uniqueness strategy

`view-transition-name` must be unique among rendered boxes at snapshot time. The
inline card and the dock both want to own "the poster" and "the play glyph". Rule:

- Assign the shared names (`--cast-vt-poster`, `--cast-vt-play`) **only to the
  element that is the morph source/target for the current transition**, set
  immediately before `startViewTransition` and cleared in its `.finished` /
  `.updateCallbackDone` handler.
- Never leave a shared name on two rendered elements simultaneously. Because at
  most one inline card per episode is on screen and there is exactly one dock,
  this is a set-before / clear-after of two elements.
- Title text and transport controls are not named; they cross-fade via the
  default root transition.

---

## The play affordance (the "episode play card")

Replaces the bare inert button under the episode. It is a projection of the dock
controller — it never instantiates a controller or `<audio>`.

### Anatomy

```
┌─────────────────────────────────────────────┐
│  ▢  Episode title (1–2 lines)                │   ▢ = poster thumb (~48px)
│  poster   ▶  Play episode · 45 min           │   ▶ = primary play, ~3.25rem
└─────────────────────────────────────────────┘
```

- **Primary play button**: larger hit target than today's 2.9rem (≥ 3.25rem / 44px
  min touch), labelled on the card ("Play episode") rather than a bare icon, with
  the same springy press already in the CSS.
- **Duration / "X min"** shown up front so the reader knows the commitment.
- **Poster thumbnail** from the existing payload `poster` (rendered only if
  present). Carries `--cast-vt-poster` during a forward morph.

### States

The card reflects the *global* controller, read through the existing read-only
controller API + events (`play`, `pause`, `timeupdate`) via the player registry —
no second controller, no duplicate keyboard handlers.

1. **Idle** — nothing playing, or a *different* episode is in the dock. Shows
   "▶ Play episode · 45 min". Click → start this episode (forward morph + source
   load/switch).
2. **Buffering** — pressed but audio not yet playable. Play glyph swaps to a
   determinate-less spinner ring; `aria-busy="true"`; status region announces
   "Loading". (Today there is no loading feedback at all — this is the smallest
   high-value play-button improvement and is independent of the morph.)
3. **Active (this episode)** — this episode is the one in the dock. The card
   collapses to a compact mirrored strip: ⏸/▶ proxy + `elapsed / total`, so a
   reader at the top of the article can pause/resume without scrolling to the
   dock. The proxy toggles the *dock* controller; it shows the dock state.

The Active strip is deliberately a *thin proxy*, not a transport, to avoid two
seek bars competing. Seeking stays in the dock (and transcript/chapters).

### Play-button polish (applies in dock and card)

These apply to the persistent-mode card and dock surfaces only. The buffering
state lives on the shared `<cast-audio-player>` element, so page-local mode
*could* adopt the same feedback for free, but doing so is an explicit,
out-of-scope follow-up here — this design does not change the page-local default.

- Buffering ring (above).
- Optional thin **progress ring** around the dock's play button using
  `--cast-progress`, doubling as a compact progress indicator where the dock is
  tight (mobile). Opt-in via a class so themes that dislike it can drop it.
- Larger touch target; existing accent tokens and `:active` spring kept.
- `prefers-reduced-motion`: ring/spinner degrade to a static state change.

---

## The dock (single live player)

The dock is the existing `<cast-audio-player>` plus the title/poster the page can
no longer supply once it scrolls away. The payload already carries `title`,
`subtitle`, and `poster`, so no backend payload change is required.

### Collapsed dock (default)

```
┌───────────────────────────────────────────────────────────────┐
│ ▢  Title — Subtitle        ⏸   ▁▁▁▁▃▁▁▁  12:34  −32:26   ⌃  ✕ │
└───────────────────────────────────────────────────────────────┘
   poster                    play  seek           times  expand close
```

- Poster (carries `--cast-vt-poster` as the morph target), one-line title.
- Play/pause (carries `--cast-vt-play`), seek, elapsed + remaining (reuses the
  current transport markup/classes).
- **Expand (⌃)** reveals the transcript/chapters panels as an upward sheet —
  reuses the existing `cast-transcript` / `cast-chapters` panel components.
- **Close (✕)** dismisses the dock entirely: it stops playback and **unmounts the
  single live controller and its `<audio>`**, leaving zero live players — distinct
  from pause, which keeps the controller alive (still the one live player, paused)
  so playback can resume. Close reverse-morphs to the active episode's card if it
  is on screen, otherwise slides the dock off the bottom edge. This is the only
  transition from one live player to zero; the "at most one" invariant holds at
  every step.

### Responsive

- Desktop: single row as above.
- Mobile: poster + title + play on row one, seek + times on row two; or the
  progress ring around the play button replaces the inline seek to save space.

---

## The morph

> **As-built note (staging, 2026-06-10).** The shipped python-podcast staging
> implementation simplified this section deliberately; the rest of this section is
> the original design intent. The actual behaviour:
> - **Forward morph is poster-only.** Only the poster carries a
>   `view-transition-name` (`cast-vt-poster`); the play glyph is *not* morphed
>   (avoids an awkward shape morph and shrinks the name-collision surface). The
>   dock's entrance on a first open is a separate `cast-vt-dock` enter animation;
>   an in-place episode switch only crossfades (no re-rise). `cast-vt-play` is
>   unused.
> - **Close is a sink + teardown, not a reverse morph.** Dismissing animates the
>   dock down (`cast-dock-sink`) and unmounts the single controller to zero live
>   players; it does not morph the poster back into the card.
> - Name assignment is generation-scoped and cleared on `finished`, so a rapid
>   second activation cannot leave two elements sharing `cast-vt-poster`.

### Forward (press play in a card)

1. Read `prefers-reduced-motion` and `document.startViewTransition` support. If
   either is absent → run the DOM update directly (no transition) and return.
2. Set `--cast-vt-poster` / `--cast-vt-play` on the **card's** poster and play
   glyph.
3. `document.startViewTransition(() => { /* DOM update */ })` where the update:
   reveals/mounts the dock, loads or switches the dock controller's source,
   moves the shared names onto the **dock's** poster/play, and collapses the card
   to its Active strip.
4. In `.finished`, clear the shared names from both ends.

Result: the poster and play glyph travel from the article into the dock while the
dock surface fades/slides up and the card content cross-fades to the Active strip.

### Reverse (dismiss)

If the active episode's card is on screen, run the inverse transition (names on
dock → names on card, dock retired). Otherwise the dock slides off the bottom
edge (no shared element to morph to).

### Across enhanced navigation

The dock lives outside the swapped content and is never re-rendered (proven). On
landing on episode B while A plays, B's card is **Idle**; pressing it morphs B's
poster into the dock and switches the source — the same forward path, just with a
source switch instead of a first load. Navigation itself never morphs the player.

---

## Single-controller invariant

- At most one live `<cast-audio-player>` (the dock) and one `<audio>`: one while
  the dock is active, zero after Close dismisses it. Switching episodes replaces
  that single instance; it never coexists with a second.
- Episode cards are projections: they subscribe to the dock controller via the
  existing registry (`whenController`) and its events, and act on it via the
  public API (`toggle`, `seek`, `getShareState`). They never construct a
  controller, register global keyboard handlers, or hold a second `<audio>`.
- A card *does* add listeners (its registry subscription plus the controller
  events it mirrors), so it owns a **bounded, self-disposing teardown surface**:
  each card registers exactly one disposer and runs it in its own
  `disconnectedCallback`. Because enhanced navigation swaps card DOM out, and an
  overview page can mount several cards, this disposal is mandatory — without it,
  cards would leak listeners and update detached DOM across navigations. The
  manager re-wires cards on `htmx:afterSettle` (as the proof already does for the
  play action), and each retired card disposes itself.
- The *controller's* own listener-disposer count therefore stays stable: cards
  attach and detach symmetrically around the single controller, which is created
  once per docked episode and unmounted once on Close. This preserves the proof's
  verified guarantees (one host, one audio, no duplicate controller-id warnings,
  stable controller-side disposer count); the only new surface is the per-card
  disposer, which is covered by the same kind of count assertion in tests.

## Accessibility

- The morph is purely presentational; focus, DOM order, and labels do not depend
  on it. Under `prefers-reduced-motion` the morph is skipped entirely.
- Buffering uses `aria-busy` + the existing polite status region; no new live
  region churn.
- The dock is a labelled `role="region"` (as in the proof). The Active strip's
  proxy button has a clear `aria-label` reflecting state ("Pause" / "Play").
- Focus is not stolen by the dock appearing; keyboard shortcuts remain owned by
  the single dock player (no duplicate handlers from cards).
- Target sizes meet 44px; the larger primary button improves the current 2.9rem.
- Axe baseline must stay at 0 new violations (the proof's bar).

## Progressive enhancement & fallback ladder

1. No JS / page-local mode → unchanged shipped behaviour.
2. Persistent mode, no View Transitions API or reduced motion → dock appears /
   updates with no animation (today's behaviour). **Floor never regresses.**
3. Persistent mode, View Transitions API + motion OK → the morph.

The buffering-ring and larger/labelled play button are independent of the morph:
they apply to the persistent-mode card and dock at both rung 2 and rung 3, so the
"better play button" half of the goal lands even on browsers where the morph
itself does not (rung 2). They do not touch page-local mode (rung 1).

## Theming

All new surfaces consume the existing `--cast-player-*` tokens (and add
`--cast-dock-*` for dock-specific spacing/edge). No tokens are declared on the
components themselves (host overrides must win, per the current CSS contract).
The progress ring reuses `--cast-progress`.

## Files this would touch (when implemented — not in this design step)

- `javascript/src/audio/custom-player.css` — play-button polish, card, dock,
  `::view-transition` group styles, reduced-motion guards.
- `javascript/src/audio/audio-player-element.ts` — buffering state, optional
  progress ring, dock title/poster rendering from payload.
- New small module for the episode card projection + morph orchestration
  (registry subscription, `startViewTransition` wrapper, name set/clear).
- Templates: the publish-only card partial (generalising the proof's
  `_persistent_play_action.html`) and the dock region partial.
- The persistent manager (proof) would call the morph wrapper instead of toggling
  `hidden`.

No backend payload change: `title`/`subtitle`/`poster`/`duration` already exist
in `build_player_payload`.

## Open questions

1. **Generalisation boundary** — does the morph wrapper ship in the cast Vite
   bundle (so any theme gets it) while site-specific navigation rules stay
   per-site? (Mirrors the proof's existing open question.)
2. **Progress ring default** — on by default in the dock on mobile, or strictly
   opt-in per theme?
3. **Dismiss semantics** — should Close stop playback, or only hide the dock while
   keeping audio alive behind a "resume" affordance? (Proposed: Close tears down;
   pause keeps the dock.)
4. **Multiple cards per page** — list/overview pages can show several episode
   cards. Only the active episode's card enters the Active state; all others stay
   Idle. Confirm this is the desired affordance on overview pages.
