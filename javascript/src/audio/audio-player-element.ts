// <cast-audio-player> — owns data parsing, the <audio> element, the
// AudioController, registration, the transport UI, the read-only public API
// (for one-way readers such as share UI), and fallback transcript hydration.

import { AudioController } from "./audio-controller";
import { formatTime, spokenTime } from "./format";
import { registerController, unregisterController } from "./player-registry";
import { isFallbackTranscript, type PlayerPayload } from "./types";

const PUBLIC_EVENT_THROTTLE_MS = 250;
const SEEK_STEP_SECONDS = 5;

const PLAY_ICON =
  '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>';
const PAUSE_ICON =
  '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor" aria-hidden="true"><path d="M6 5h4v14H6zM14 5h4v14h-4z"/></svg>';

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

export class CastAudioPlayerElement extends HTMLElement {
  controller?: AudioController;
  private playerId = "";
  private disabled = false;
  private audioEl?: HTMLAudioElement;
  private playButton?: HTMLButtonElement;
  private range?: HTMLInputElement;
  private output?: HTMLOutputElement;
  private statusRegion?: HTMLElement;
  private controllerListeners: Array<[string, EventListener]> = [];
  private audioListeners: Array<[string, EventListener]> = [];
  private keydownListener?: EventListener;
  private lastPublicEmit = Number.NEGATIVE_INFINITY;
  private publicTimer: ReturnType<typeof setTimeout> | null = null;

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
    registerController(this.playerId, this.controller);

    this.renderTransport(payload);
    this.subscribe();
    if (!this.disabled) {
      this.installKeyboardShortcuts();
    }

    if (isFallbackTranscript(payload.transcript)) {
      void this.hydrateFromUrl(payload.transcript.url);
    }
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
    if (this.keydownListener) {
      this.removeEventListener("keydown", this.keydownListener);
      this.keydownListener = undefined;
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
    playButton.addEventListener("click", () => this.controller?.toggle());
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
        this.controller.seek(range.valueAsNumber);
      }
    });
    this.range = range;

    const output = el("output", "cast-player__time");
    output.textContent = `${formatTime(0)} / ${known ? formatTime(payload.duration as number) : "--:--"}`;
    this.output = output;

    const status = el("div", "cast-player__status", { role: "status", "aria-live": "polite" });
    this.statusRegion = status;

    transport.append(playButton, range, output);
    this.appendChild(transport);
    this.appendChild(status);

    if (this.disabled) {
      const message = el("p", "cast-player__unavailable");
      message.textContent = "Audio unavailable.";
      this.appendChild(message);
    } else {
      this.appendChild(this.renderShortcutsHelp());
    }
  }

  private renderShortcutsHelp(): HTMLElement {
    const details = el("details", "cast-player__shortcuts");
    const summary = el("summary");
    summary.textContent = "Keyboard shortcuts";
    const list = el("ul");
    for (const line of [
      "Space or K: play / pause",
      "Left / Right arrow: skip 5 seconds",
      "Home / End: start / end",
    ]) {
      const item = el("li");
      item.textContent = line;
      list.appendChild(item);
    }
    details.append(summary, list);
    return details;
  }

  // ---- controller subscription ---------------------------------------------

  private subscribe(): void {
    const controller = this.controller;
    if (!controller) {
      return;
    }
    this.on("play", () => this.onPlayState(true));
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
    }
    if (this.output) {
      this.output.textContent = `${formatTime(t)} / ${typeof duration === "number" ? formatTime(duration) : "--:--"}`;
    }
    this.emitPublicTimeUpdate(t, duration);
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
      if (this.output) {
        this.output.textContent = `${formatTime(controller.currentTime)} / ${formatTime(duration)}`;
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

  private installKeyboardShortcuts(): void {
    const listener = ((event: KeyboardEvent) => this.onKeydown(event)) as EventListener;
    this.addEventListener("keydown", listener);
    this.keydownListener = listener;
  }

  private onKeydown(event: KeyboardEvent): void {
    const controller = this.controller;
    if (!controller || this.disabled) {
      return;
    }
    // The native range handles its own arrows/Home/End and is unaffected by
    // Space; never intercept while it is focused.
    const onRange = event.target === this.range;
    switch (event.key) {
      case " ":
      case "k":
      case "K":
        if (onRange) {
          return;
        }
        event.preventDefault();
        controller.toggle();
        break;
      case "ArrowLeft":
        if (onRange) {
          return;
        }
        event.preventDefault();
        controller.seek(controller.currentTime - SEEK_STEP_SECONDS);
        break;
      case "ArrowRight":
        if (onRange) {
          return;
        }
        event.preventDefault();
        controller.seek(controller.currentTime + SEEK_STEP_SECONDS);
        break;
      case "Home":
        if (onRange) {
          return;
        }
        event.preventDefault();
        controller.seek(0);
        break;
      case "End": {
        if (onRange) {
          return;
        }
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
    try {
      const response = await fetch(url);
      if (!response.ok) {
        return;
      }
      const data = (await response.json()) as { cues?: unknown };
      if (this.controller && Array.isArray(data.cues)) {
        this.controller.setCues(data.cues as never);
      }
    } catch {
      // Network/parse failure: leave the transcript empty. The page still has
      // the no-JS transcript pages as a fallback.
    }
  }
}

export const CAST_AUDIO_PLAYER_TAG = "cast-audio-player";

export function defineCastAudioPlayer(): void {
  if (!customElements.get(CAST_AUDIO_PLAYER_TAG)) {
    customElements.define(CAST_AUDIO_PLAYER_TAG, CastAudioPlayerElement);
  }
}
