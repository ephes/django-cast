// <cast-audio-player> — owns data parsing, the <audio> element, the
// AudioController, registration, the transport UI, the read-only public API
// (for one-way readers such as share UI), and fallback transcript hydration.

import { AudioController } from "./audio-controller";
import { formatTime, spokenTime } from "./format";
import { registerController, unregisterController } from "./player-registry";
import type { PlayerPayload } from "./types";

const PUBLIC_EVENT_THROTTLE_MS = 250;
const SEEK_STEP_SECONDS = 5;

const PLAY_ICON =
  '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>';
const PAUSE_ICON =
  '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor" aria-hidden="true"><path d="M6 5h4v14H6zM14 5h4v14h-4z"/></svg>';
const SHARE_ICON =
  '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="M8.6 13.5l6.8 4M15.4 6.5l-6.8 4"/></svg>';
const KEYBOARD_ICON =
  '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/></svg>';

const SHORTCUTS: ReadonlyArray<[string, string]> = [
  ["Space / K", "play / pause"],
  ["← / →", "skip 5 seconds"],
  ["Home / End", "start / end"],
];

function timecode(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  const m = Math.floor(whole / 60);
  const s = whole % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function parseTimecode(raw: string): number | null {
  const match = /^(\d{1,3}):([0-5]\d)$/.exec(raw.trim());
  return match ? Number(match[1]) * 60 + Number(match[2]) : null;
}

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  attrs?: Record<string, string>,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) {
    node.className = className;
  }
  if (attrs) {
    for (const [key, value] of Object.entries(attrs)) {
      node.setAttribute(key, value);
    }
  }
  return node;
}

// ---- episode-page-global keyboard shortcuts ---------------------------------
// The transport shortcuts (Space/K, ←/→, Home/End) act on the active player
// from anywhere on the page, so the reader can pause or scrub while reading the
// transcript or show notes without first focusing the player. A single
// document-level listener — installed once and shared by every player — routes
// each keypress to the player the reader last engaged with; with the usual
// single player per page that is simply that player. Keypresses are ignored
// whenever focus is on an interactive control (form fields, buttons, links, the
// transcript search) so typing and native button/link activation are untouched.
const connectedPlayers = new Set<CastAudioPlayerElement>();
let activePlayer: CastAudioPlayerElement | null = null;
let documentKeydownInstalled = false;

function resolveShortcutPlayer(target: EventTarget | null): CastAudioPlayerElement | null {
  // A keypress originating inside a specific player acts on that player.
  if (target instanceof Element) {
    const owner = target.closest("cast-audio-player");
    if (owner instanceof CastAudioPlayerElement && connectedPlayers.has(owner)) {
      return owner;
    }
  }
  if (activePlayer && connectedPlayers.has(activePlayer)) {
    return activePlayer;
  }
  // Otherwise route to the only player on the page, if there is exactly one.
  return connectedPlayers.size === 1 ? (connectedPlayers.values().next().value ?? null) : null;
}

function onDocumentKeydown(event: KeyboardEvent): void {
  // Never claim a modified keypress: Cmd/Ctrl/Alt/Shift + arrow/Home/End/Space are
  // browser and OS navigation shortcuts (back/forward, scroll, etc.). The bare
  // transport keys are the only ones the player owns page-wide.
  if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) {
    return;
  }
  const target = event.target as HTMLElement | null;
  // Let native controls keep their own keys: form fields, buttons, links, and
  // the transcript search must never have Space/arrows/Home/End hijacked.
  if (target && target.closest("input, button, select, textarea, a[href], [contenteditable]")) {
    return;
  }
  resolveShortcutPlayer(target)?.handleShortcut(event);
}

function ensureDocumentKeydown(): void {
  if (documentKeydownInstalled) {
    return;
  }
  document.addEventListener("keydown", onDocumentKeydown);
  documentKeydownInstalled = true;
}

export class CastAudioPlayerElement extends HTMLElement {
  controller?: AudioController;
  private playerId = "";
  private disabled = false;
  private audioEl?: HTMLAudioElement;
  private playButton?: HTMLButtonElement;
  private range?: HTMLInputElement;
  private output?: HTMLOutputElement;
  private remaining?: HTMLOutputElement;
  private statusRegion?: HTMLElement;
  private controllerListeners: Array<[string, EventListener]> = [];
  private audioListeners: Array<[string, EventListener]> = [];
  private lastPublicEmit = Number.NEGATIVE_INFINITY;
  private publicTimer: ReturnType<typeof setTimeout> | null = null;
  private shareDialog?: HTMLDialogElement;
  private shareTimeInput?: HTMLInputElement;
  private shareBuildUrl?: () => void;
  private fetchingTranscript = false;

  connectedCallback(): void {
    if (this.controller) {
      return; // already initialised (re-connect without disconnect)
    }
    const payload = this.readPayload();
    if (!payload) {
      return;
    }
    this.playerId = this.id;
    this.disabled = payload.sources.length === 0;

    const audio = el("audio");
    audio.preload = "metadata";
    for (const source of payload.sources) {
      const sourceEl = el("source");
      sourceEl.type = source.type;
      sourceEl.src = source.src;
      audio.appendChild(sourceEl);
    }
    this.audioEl = audio;
    this.appendChild(audio);

    this.controller = new AudioController(audio, payload);
    // Install the transcript-fetch listener BEFORE registerController() — that
    // call dispatches cast:player-ready and can synchronously resolve a
    // persisted-open <cast-transcript> that immediately calls
    // requestTranscript(); installing first makes the request impossible to miss.
    const onTranscriptRequest = ((event: Event) => {
      const url = (event as CustomEvent<{ url: string }>).detail?.url;
      if (url) {
        void this.hydrateFromUrl(url);
      }
    }) as EventListener;
    this.controller.addEventListener("transcriptrequested", onTranscriptRequest);
    this.controllerListeners.push(["transcriptrequested", onTranscriptRequest]);

    registerController(this.playerId, this.controller);

    this.renderTransport(payload);
    this.subscribe();
    if (!this.disabled) {
      // Keyboard shortcuts are page-global (see the document-level listener
      // above): the reader never has to focus the player first. The element is
      // still made focusable and labelled so it remains a discoverable, keyboard-
      // reachable control in the tab order, and so a keypress that does originate
      // inside it routes to it specifically.
      this.tabIndex = 0;
      this.setAttribute("role", "group");
      this.setAttribute("aria-label", "Audio player");
      this.setAttribute("aria-keyshortcuts", "Space K ArrowLeft ArrowRight Home End");
      connectedPlayers.add(this);
      // Deliberately do NOT mark this player active on connect: with a single
      // player the document handler falls back to "the only player", and with
      // several players the global shortcuts stay inert until the reader engages
      // one (play/scrub) — so connection order never silently decides the target.
      ensureDocumentKeydown();
      this.applyStartAt();
    }
    // No eager transcript fetch on connect (revision 4): the transcript loads
    // only when the user first opens the panel, via requestTranscript().
  }

  disconnectedCallback(): void {
    for (const [name, listener] of this.controllerListeners) {
      this.controller?.removeEventListener(name, listener);
    }
    this.controllerListeners = [];
    for (const [name, listener] of this.audioListeners) {
      this.audioEl?.removeEventListener(name, listener);
    }
    this.audioListeners = [];
    connectedPlayers.delete(this);
    if (activePlayer === this) {
      activePlayer = null;
    }
    if (this.publicTimer !== null) {
      clearTimeout(this.publicTimer);
      this.publicTimer = null;
    }
    if (this.controller) {
      unregisterController(this.playerId, this.controller);
      this.controller.destroy();
      this.controller = undefined;
    }
  }

  // ---- public, read-only API (one-way readers such as share UI) -------------

  get currentTime(): number {
    return this.controller?.currentTime ?? 0;
  }

  get duration(): number | null {
    return this.controller?.duration ?? null;
  }

  // The in-transport share button is suppressed by `data-share="none"`. The
  // public getShareState() API below is unaffected (a host share UI can still
  // read the player time).
  private shareEnabled(): boolean {
    return this.getAttribute("data-share") !== "none";
  }

  getShareState(): { currentTime: number; duration: number | null; audioId: number } {
    return {
      currentTime: this.currentTime,
      duration: this.duration,
      audioId: this.controller?.payload.audioId ?? 0,
    };
  }

  // ---- rendering ------------------------------------------------------------

  private readPayload(): PlayerPayload | null {
    const id = this.getAttribute("data-payload");
    if (!id) {
      return null;
    }
    const script = document.getElementById(id);
    if (!script || !script.textContent) {
      return null;
    }
    try {
      return JSON.parse(script.textContent) as PlayerPayload;
    } catch {
      return null;
    }
  }

  private renderTransport(payload: PlayerPayload): void {
    const transport = el("div", "cast-player__transport");

    const playButton = el("button", "cast-player__play", { type: "button" });
    playButton.setAttribute("aria-label", "Play");
    playButton.innerHTML = PLAY_ICON;
    playButton.disabled = this.disabled;
    playButton.addEventListener("click", () => {
      activePlayer = this; // engaging a player makes its shortcuts the page-global target
      this.controller?.toggle();
      // Move focus to the player so the keyboard shortcuts (Space/K/arrows) act on
      // it immediately after the user starts playback with the mouse.
      if (!this.disabled) {
        this.focus();
      }
    });
    this.playButton = playButton;

    const range = el("input", "cast-player__seek", { type: "range" });
    range.min = "0";
    range.step = "1";
    range.value = "0";
    range.setAttribute("aria-label", "Seek");
    const known = typeof payload.duration === "number";
    range.max = known ? String(payload.duration) : "0";
    range.disabled = this.disabled || !known;
    range.setAttribute("aria-valuetext", known ? this.valueText(0, payload.duration) : "duration unknown");
    range.addEventListener("input", () => {
      if (this.controller) {
        activePlayer = this; // scrubbing makes this the page-global shortcut target
        this.controller.seek(range.valueAsNumber);
      }
    });
    this.range = range;

    // Elapsed sits left of the bar; remaining (−m:ss) sits right of it.
    const elapsed = el("output", "cast-player__time");
    elapsed.textContent = formatTime(0);
    this.output = elapsed;

    const remaining = el("output", "cast-player__remaining");
    remaining.textContent = known ? `-${formatTime(payload.duration as number)}` : "--:--";
    this.remaining = remaining;

    const status = el("div", "cast-player__status", { role: "status", "aria-live": "polite" });
    this.statusRegion = status;

    transport.append(playButton, elapsed, range, remaining);
    if (!this.disabled) {
      // The in-transport share button is opt-out via `data-share="none"` so a
      // host that owns a richer page-level share UI (social targets, copy,
      // Mastodon, timestamped links) can expose a single share entry point. The
      // read-only getShareState() API stays available either way, so the host
      // share UI can still read the player's current time.
      const shareEnabled = this.shareEnabled();
      if (shareEnabled) {
        const share = el("button", "cast-player__share", { type: "button" });
        share.setAttribute("aria-label", "Share with current time");
        share.innerHTML = SHARE_ICON;
        share.addEventListener("click", () => this.openShare());
        transport.appendChild(share);
      }

      const { button, popover } = this.buildShortcuts();
      transport.appendChild(button);
      this.appendChild(transport);
      this.appendChild(status);
      this.appendChild(popover);
      if (shareEnabled) {
        this.appendChild(this.buildShareDialog());
      }
      return;
    }
    this.appendChild(transport);
    this.appendChild(status);
    const message = el("p", "cast-player__unavailable");
    message.textContent = "Audio unavailable.";
    this.appendChild(message);
  }

  private remainingText(currentTime: number, duration: number | null): string {
    return typeof duration === "number" ? `-${formatTime(Math.max(0, duration - currentTime))}` : "--:--";
  }

  // ---- share with timestamp -------------------------------------------------

  private buildShareDialog(): HTMLDialogElement {
    const dialog = el("dialog", "cast-share");

    const titleId = `cast-share-title-${this.playerId || "player"}`;
    const title = el("h2", "cast-share__title", { id: titleId });
    title.textContent = "Share";
    dialog.setAttribute("aria-labelledby", titleId);

    const startRow = el("div", "cast-share__row");
    const toggleLabel = el("label", "cast-share__startat");
    const startToggle = el("input", undefined, { type: "checkbox" });
    startToggle.checked = true;
    const toggleText = el("span");
    toggleText.textContent = " Start at ";
    const timeInput = el("input", "cast-share__time", {
      type: "text",
      inputmode: "numeric",
      pattern: "[0-9]{1,3}:[0-5][0-9]",
    });
    timeInput.setAttribute("aria-label", "Start time (minutes:seconds)");
    toggleLabel.append(startToggle, toggleText, timeInput);
    startRow.appendChild(toggleLabel);

    const urlRow = el("div", "cast-share__row");
    const urlInput = el("input", "cast-share__url", { type: "text", readonly: "" });
    urlInput.setAttribute("aria-label", "Share URL");
    const copyButton = el("button", "cast-share__copy", { type: "button" });
    copyButton.textContent = "Copy";
    urlRow.append(urlInput, copyButton);

    const closeRow = el("div", "cast-share__row");
    const closeButton = el("button", "cast-share__close", { type: "button" });
    closeButton.textContent = "Close";
    closeRow.appendChild(closeButton);

    const buildUrl = () => {
      const base = new URL(window.location.href);
      base.searchParams.delete("t");
      if (startToggle.checked) {
        const seconds = parseTimecode(timeInput.value);
        if (seconds != null) {
          base.searchParams.set("t", String(seconds));
        }
      }
      urlInput.value = base.toString();
    };

    startToggle.addEventListener("change", () => {
      timeInput.disabled = !startToggle.checked;
      buildUrl();
    });
    timeInput.addEventListener("input", buildUrl);
    copyButton.addEventListener("click", () => {
      void navigator.clipboard?.writeText(urlInput.value).then(
        () => {
          copyButton.textContent = "Copied!";
          window.setTimeout(() => (copyButton.textContent = "Copy"), 1500);
        },
        () => {
          urlInput.select();
        },
      );
    });
    closeButton.addEventListener("click", () => this.closeShare());

    dialog.append(title, startRow, urlRow, closeRow);
    this.shareDialog = dialog;
    this.shareTimeInput = timeInput;
    this.shareBuildUrl = buildUrl;
    return dialog;
  }

  private openShare(): void {
    if (!this.shareDialog || !this.shareTimeInput || !this.shareBuildUrl) {
      return;
    }
    this.shareTimeInput.value = timecode(this.currentTime);
    this.shareBuildUrl();
    if (typeof this.shareDialog.showModal === "function") {
      this.shareDialog.showModal();
    } else {
      this.shareDialog.setAttribute("open", "");
    }
  }

  private closeShare(): void {
    if (!this.shareDialog) {
      return;
    }
    // Mirror the open path: only native dialogs get close(); the attribute
    // fallback is removed otherwise.
    if (this.shareDialog.hasAttribute("open") && typeof this.shareDialog.close !== "function") {
      this.shareDialog.removeAttribute("open");
    } else if (typeof this.shareDialog.close === "function") {
      this.shareDialog.close();
    }
  }

  // Seek to the ?t=<seconds> deep-link once metadata is available.
  private applyStartAt(): void {
    const raw = new URL(window.location.href).searchParams.get("t");
    if (raw === null) {
      return;
    }
    const seconds = Number(raw);
    if (!Number.isFinite(seconds) || seconds <= 0) {
      return;
    }
    const seekOnce = () => this.controller?.seek(seconds);
    if (typeof this.controller?.duration === "number") {
      seekOnce();
    } else {
      const onDuration = () => {
        this.controller?.removeEventListener("durationchange", onDuration);
        seekOnce();
      };
      this.controller?.addEventListener("durationchange", onDuration);
      this.controllerListeners.push(["durationchange", onDuration as EventListener]);
    }
  }

  // A small round button (matching share) that opens a popover listing the
  // shortcuts — replacing the old raw <details> disclosure.
  private buildShortcuts(): { button: HTMLButtonElement; popover: HTMLElement } {
    const popoverId = `cast-shortcuts-${this.playerId || "player"}`;
    const popover = el("div", "cast-player__shortcuts-popover", { id: popoverId, popover: "" });
    const heading = el("h2");
    heading.textContent = "Keyboard shortcuts";
    const list = el("ul");
    for (const [keys, description] of SHORTCUTS) {
      const item = el("li");
      const kbd = el("kbd");
      kbd.textContent = keys;
      item.append(kbd, document.createTextNode(` — ${description}`));
      list.appendChild(item);
    }
    popover.append(heading, list);

    const button = el("button", "cast-player__shortcuts-btn", { type: "button" });
    button.setAttribute("aria-label", "Keyboard shortcuts");
    button.setAttribute("popovertarget", popoverId);
    button.innerHTML = KEYBOARD_ICON;
    // The popovertarget attribute toggles natively when the API is available;
    // fall back to a data-attribute toggle otherwise (older engines, jsdom).
    button.addEventListener("click", () => {
      if (typeof (popover as { togglePopover?: () => void }).togglePopover !== "function") {
        popover.toggleAttribute("data-open");
      }
    });
    return { button, popover };
  }

  // ---- controller subscription ---------------------------------------------

  private subscribe(): void {
    const controller = this.controller;
    if (!controller) {
      return;
    }
    this.on("play", () => {
      // Playback starting — however it was triggered (transport button, keyboard,
      // or a transcript-line click that calls play()) — marks this the active
      // player, so subsequent page-global shortcuts act on what is now playing.
      activePlayer = this;
      this.onPlayState(true);
    });
    // A transcript- or chapter-line navigation is engagement too. It is the only
    // signal that marks the active player when the clicked line is in a player
    // that is ALREADY playing: play() then fires no new "play" event, but
    // seekToCue()/seekToChapter() emit "navseek". This is deliberately NOT the
    // generic "seeking" event — the initial ?t= deep-link uses the low-level
    // seek(), so loading a multi-player page with a timestamp must not silently
    // mark a player active. Scrub and keyboard seeks set activePlayer at their
    // own (user-gesture) call sites.
    this.on("navseek", () => {
      activePlayer = this;
    });
    this.on("pause", () => this.onPlayState(false));
    this.on("timeupdate", () => this.onTimeUpdate());
    this.on("durationchange", () => this.onDurationChange());

    // Buffering state from the media element, kept minimal and layout-stable.
    this.onAudio("waiting", () => this.setStatus("Loading…"));
    this.onAudio("playing", () => this.setStatus("Playing"));
  }

  private on(type: string, listener: () => void): void {
    this.controller?.addEventListener(type, listener as EventListener);
    this.controllerListeners.push([type, listener as EventListener]);
  }

  private onAudio(type: string, listener: () => void): void {
    this.audioEl?.addEventListener(type, listener as EventListener);
    this.audioListeners.push([type, listener as EventListener]);
  }

  private onPlayState(playing: boolean): void {
    if (this.playButton) {
      this.playButton.setAttribute("aria-label", playing ? "Pause" : "Play");
      this.playButton.innerHTML = playing ? PAUSE_ICON : PLAY_ICON;
    }
    this.setStatus(playing ? "Playing" : "Paused");
  }

  private onTimeUpdate(): void {
    const controller = this.controller;
    if (!controller) {
      return;
    }
    const t = controller.currentTime;
    const duration = controller.duration;
    if (this.range && !this.range.matches(":active")) {
      this.range.value = String(Math.floor(t));
    }
    if (this.range) {
      this.range.setAttribute("aria-valuetext", typeof duration === "number" ? this.valueText(t, duration) : spokenTime(t));
      this.updateProgressFill(t, duration);
    }
    if (this.output) {
      this.output.textContent = formatTime(t);
    }
    if (this.remaining) {
      this.remaining.textContent = this.remainingText(t, duration);
    }
    this.emitPublicTimeUpdate(t, duration);
  }

  // Paint the accent fill of the custom range track via a CSS variable.
  private updateProgressFill(currentTime: number, duration: number | null): void {
    if (!this.range) {
      return;
    }
    const pct = typeof duration === "number" && duration > 0 ? Math.min(100, (currentTime / duration) * 100) : 0;
    this.range.style.setProperty("--cast-progress", `${pct}%`);
  }

  private onDurationChange(): void {
    const controller = this.controller;
    if (!controller || !this.range) {
      return;
    }
    const duration = controller.duration;
    if (typeof duration === "number") {
      this.range.max = String(duration);
      this.range.disabled = this.disabled;
      this.range.setAttribute("aria-valuetext", this.valueText(controller.currentTime, duration));
      this.updateProgressFill(controller.currentTime, duration);
      if (this.output) {
        this.output.textContent = formatTime(controller.currentTime);
      }
      if (this.remaining) {
        this.remaining.textContent = this.remainingText(controller.currentTime, duration);
      }
    }
  }

  private valueText(currentTime: number, duration: number | null): string {
    if (typeof duration !== "number") {
      return spokenTime(currentTime);
    }
    return `${spokenTime(currentTime)} of ${spokenTime(duration)}`;
  }

  private setStatus(text: string): void {
    if (this.statusRegion) {
      this.statusRegion.textContent = text;
    }
  }

  // ---- public throttled event ----------------------------------------------

  private emitPublicTimeUpdate(currentTime: number, duration: number | null): void {
    const now = Date.now();
    const elapsed = now - this.lastPublicEmit;
    const fire = () => {
      this.lastPublicEmit = Date.now();
      this.publicTimer = null;
      this.dispatchEvent(
        new CustomEvent("cast:timeupdate", {
          bubbles: true,
          composed: true,
          detail: { currentTime: this.currentTime, duration: this.duration },
        }),
      );
    };
    if (elapsed >= PUBLIC_EVENT_THROTTLE_MS) {
      fire();
    } else if (this.publicTimer === null) {
      this.publicTimer = setTimeout(fire, PUBLIC_EVENT_THROTTLE_MS - elapsed);
    }
  }

  // ---- keyboard -------------------------------------------------------------

  // Apply a transport shortcut to this player. Called by the shared
  // document-level keydown listener (onDocumentKeydown), which has already
  // resolved the target player and skipped keypresses aimed at interactive
  // controls, so this only has to act on the key.
  handleShortcut(event: KeyboardEvent): void {
    const controller = this.controller;
    if (!controller || this.disabled) {
      return;
    }
    const handled =
      event.key === " " ||
      event.key === "k" ||
      event.key === "K" ||
      event.key === "ArrowLeft" ||
      event.key === "ArrowRight" ||
      event.key === "Home" ||
      event.key === "End";
    if (!handled) {
      return; // unrecognised key — leave it for the page, do not mark engagement
    }
    // A handled transport key is engagement: remember this as the active player so
    // later page-global shortcuts keep targeting the one the reader is driving.
    activePlayer = this;
    switch (event.key) {
      case " ":
      case "k":
      case "K":
        event.preventDefault();
        controller.toggle();
        break;
      case "ArrowLeft":
        event.preventDefault();
        controller.seek(controller.currentTime - SEEK_STEP_SECONDS);
        break;
      case "ArrowRight":
        event.preventDefault();
        controller.seek(controller.currentTime + SEEK_STEP_SECONDS);
        break;
      case "Home":
        event.preventDefault();
        controller.seek(0);
        break;
      case "End": {
        const duration = controller.duration;
        if (typeof duration === "number") {
          event.preventDefault();
          controller.seek(duration);
        }
        break;
      }
      default:
        break;
    }
  }

  // ---- fallback hydration ---------------------------------------------------

  private async hydrateFromUrl(url: string): Promise<void> {
    if (this.fetchingTranscript) {
      return; // at most one fetch in flight
    }
    this.fetchingTranscript = true;
    try {
      const response = await fetch(url);
      if (!response.ok) {
        this.controller?.transcriptFailed();
        return;
      }
      const data = (await response.json()) as { cues?: unknown };
      if (this.controller && Array.isArray(data.cues)) {
        this.controller.setCues(data.cues as never);
      } else {
        this.controller?.transcriptFailed();
      }
    } catch {
      // Network/parse failure: clear loading so a later open can retry. The page
      // still has the no-JS transcript pages as a deeper fallback.
      this.controller?.transcriptFailed();
    } finally {
      this.fetchingTranscript = false;
    }
  }
}

export const CAST_AUDIO_PLAYER_TAG = "cast-audio-player";

export function defineCastAudioPlayer(): void {
  if (!customElements.get(CAST_AUDIO_PLAYER_TAG)) {
    customElements.define(CAST_AUDIO_PLAYER_TAG, CastAudioPlayerElement);
  }
}
