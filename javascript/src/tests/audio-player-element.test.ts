import { beforeEach, describe, expect, it, vi } from "vitest";

import "@/audio/custom-player";
import { _clearRegistry } from "@/audio/player-registry";
import type { PlayerPayload } from "@/audio/types";
import { installMediaMock, installSyncRaf } from "./media-mock";

function makePayload(overrides: Partial<PlayerPayload> = {}): PlayerPayload {
  return {
    audioId: 7,
    title: "Episode",
    subtitle: "",
    duration: 60,
    poster: "",
    sources: [{ type: "audio/mp4", src: "/a.m4a" }],
    chapters: [],
    transcript: { cues: [] },
    ...overrides,
  };
}

function mountPlayer(payload: PlayerPayload, id = "cast-player-7") {
  const dataId = `cast-player-data-${payload.audioId}`;
  const script = document.createElement("script");
  script.type = "application/json";
  script.id = dataId;
  script.textContent = JSON.stringify(payload);
  document.body.appendChild(script);

  const player = document.createElement("cast-audio-player");
  player.id = id;
  player.setAttribute("data-payload", dataId);
  document.body.appendChild(player);
  return player as HTMLElement & {
    controller?: import("@/audio/audio-controller").AudioController;
    currentTime: number;
    duration: number | null;
    getShareState(): { currentTime: number; duration: number | null; audioId: number };
  };
}

function audioOf(player: HTMLElement): HTMLAudioElement {
  return player.querySelector("audio") as HTMLAudioElement;
}

beforeEach(() => {
  document.body.innerHTML = "";
  _clearRegistry();
  installMediaMock();
  installSyncRaf();
  vi.useRealTimers();
});

describe("cast-audio-player transport", () => {
  it("uses preload=metadata and one source per format", () => {
    const player = mountPlayer(makePayload({ sources: [{ type: "audio/mp4", src: "/a.m4a" }] }));
    const audio = audioOf(player);
    expect(audio.preload).toBe("metadata");
    expect(audio.querySelectorAll("source")).toHaveLength(1);
  });

  it("toggles play/pause label and state", () => {
    const player = mountPlayer(makePayload());
    const button = player.querySelector(".cast-player__play") as HTMLButtonElement;
    expect(button.getAttribute("aria-label")).toBe("Play");
    button.click();
    expect(button.getAttribute("aria-label")).toBe("Pause");
    button.click();
    expect(button.getAttribute("aria-label")).toBe("Play");
  });

  it("range input calls seek and shows tabular time, with no aria-live on time", () => {
    const player = mountPlayer(makePayload({ duration: 75 }));
    const range = player.querySelector(".cast-player__seek") as HTMLInputElement;
    const output = player.querySelector(".cast-player__time") as HTMLOutputElement;
    expect(range.max).toBe("75");
    expect(output.hasAttribute("aria-live")).toBe(false);
    range.value = "65";
    range.dispatchEvent(new Event("input"));
    expect(audioOf(player).currentTime).toBe(65);
    expect(output.textContent).toBe("1:05 / 1:15");
    expect(range.getAttribute("aria-valuetext")).toContain("of");
  });

  it("formats hours as h:mm:ss", () => {
    const player = mountPlayer(makePayload({ duration: 3725 }));
    const output = player.querySelector(".cast-player__time") as HTMLOutputElement;
    expect(output.textContent).toBe("0:00 / 1:02:05");
  });

  it("duration-unknown disables the range and shows --:--, then enables on durationchange", () => {
    const player = mountPlayer(makePayload({ duration: null }));
    const range = player.querySelector(".cast-player__seek") as HTMLInputElement;
    const output = player.querySelector(".cast-player__time") as HTMLOutputElement;
    expect(range.disabled).toBe(true);
    expect(range.max).toBe("0");
    expect(range.getAttribute("aria-valuetext")).toBe("duration unknown");
    expect(output.textContent).toContain("--:--");

    const audio = audioOf(player);
    audio.duration = 90;
    audio.dispatchEvent(new Event("durationchange"));
    expect(range.disabled).toBe(false);
    expect(range.max).toBe("90");
    expect(output.textContent).toBe("0:00 / 1:30");
  });

  it("no-sources renders a disabled state with an unavailable message", () => {
    const player = mountPlayer(makePayload({ sources: [] }));
    const button = player.querySelector(".cast-player__play") as HTMLButtonElement;
    const range = player.querySelector(".cast-player__seek") as HTMLInputElement;
    expect(button.disabled).toBe(true);
    expect(range.disabled).toBe(true);
    expect(player.querySelector(".cast-player__unavailable")).not.toBeNull();
  });

  it("keyboard shortcuts toggle and seek, scoped to the player", () => {
    const player = mountPlayer(makePayload({ duration: 100 }));
    const audio = audioOf(player);
    audio.currentTime = 20;
    player.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    expect(audio.currentTime).toBe(25);
    player.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowLeft", bubbles: true }));
    expect(audio.currentTime).toBe(20);
    player.dispatchEvent(new KeyboardEvent("keydown", { key: "Home", bubbles: true }));
    expect(audio.currentTime).toBe(0);
    player.dispatchEvent(new KeyboardEvent("keydown", { key: "End", bubbles: true }));
    expect(audio.currentTime).toBe(100);
    const button = player.querySelector(".cast-player__play") as HTMLButtonElement;
    player.dispatchEvent(new KeyboardEvent("keydown", { key: "k", bubbles: true }));
    expect(button.getAttribute("aria-label")).toBe("Pause");
  });

  it("does not intercept arrows when the range is focused", () => {
    const player = mountPlayer(makePayload({ duration: 100 }));
    const range = player.querySelector(".cast-player__seek") as HTMLInputElement;
    const audio = audioOf(player);
    audio.currentTime = 20;
    const event = new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true, cancelable: true });
    Object.defineProperty(event, "target", { value: range });
    player.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
    expect(audio.currentTime).toBe(20);
  });
});

describe("cast-audio-player public API", () => {
  it("exposes read-only getters and getShareState", () => {
    const player = mountPlayer(makePayload({ duration: 60 }));
    audioOf(player).currentTime = 12;
    expect(player.currentTime).toBe(12);
    expect(player.duration).toBe(60);
    expect(player.getShareState()).toEqual({ currentTime: 12, duration: 60, audioId: 7 });
  });

  it("emits a throttled, bubbling, composed cast:timeupdate (~250ms)", () => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
    installSyncRaf(); // useFakeTimers re-fakes rAF; keep it synchronous
    const player = mountPlayer(makePayload({ duration: 100 }));
    const events: number[] = [];
    document.addEventListener("cast:timeupdate", (e) => events.push((e as CustomEvent).detail.currentTime));
    const audio = audioOf(player);

    audio.currentTime = 1;
    audio.dispatchEvent(new Event("timeupdate")); // first fires immediately
    expect(events).toEqual([1]);

    audio.currentTime = 2;
    audio.dispatchEvent(new Event("timeupdate")); // throttled
    expect(events).toEqual([1]);

    vi.advanceTimersByTime(250);
    expect(events.length).toBe(2);
    vi.useRealTimers();
  });
});

describe("cast-audio-player lifecycle", () => {
  it("registers and destroys the controller across disconnect", () => {
    const player = mountPlayer(makePayload());
    expect(player.controller).toBeDefined();
    player.remove();
    expect(player.controller).toBeUndefined();
  });

  it("warns and last-wins on duplicate id", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const first = mountPlayer(makePayload(), "cast-player-7");
    const firstController = first.controller;
    const second = mountPlayer(makePayload(), "cast-player-7");
    expect(warn).toHaveBeenCalled();
    expect(second.controller).not.toBe(firstController);
    warn.mockRestore();
  });
});

describe("cast-audio-player fallback hydration", () => {
  it("fetches the url once and installs cues via setCues", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ cues: [{ start: 0, end: 1, speaker: "", text: "late" }] }),
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const player = mountPlayer(makePayload({ transcript: { url: "/api/audios/7/player-transcript/" } }));
    expect(player.controller?.transcriptPending).toBe(true);
    await vi.waitFor(() => expect(player.controller?.getCues().length).toBe(1));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(player.controller?.transcriptPending).toBe(false);
    vi.unstubAllGlobals();
  });
});

describe("cast-audio-player share with timestamp", () => {
  it("opens a share dialog prefilled with the current time and a ?t= link", () => {
    const player = mountPlayer(makePayload({ duration: 600 }));
    const audio = audioOf(player);
    audio.currentTime = 125; // 2:05
    const share = player.querySelector(".cast-player__share") as HTMLButtonElement;
    const dialog = player.querySelector("dialog.cast-share") as HTMLDialogElement;
    // the dialog has an accessible name via aria-labelledby -> the Share heading
    const labelledby = dialog.getAttribute("aria-labelledby");
    expect(labelledby).toBeTruthy();
    expect(dialog.querySelector(`#${labelledby}`)?.textContent).toBe("Share");
    share.click();
    expect(dialog.hasAttribute("open")).toBe(true); // jsdom has no showModal -> open fallback
    const time = dialog.querySelector(".cast-share__time") as HTMLInputElement;
    const url = dialog.querySelector(".cast-share__url") as HTMLInputElement;
    expect(time.value).toBe("2:05");
    expect(url.value).toContain("t=125");

    // Close mirrors the open fallback (jsdom has no showModal/close -> open attr).
    const close = dialog.querySelector(".cast-share__close") as HTMLButtonElement;
    close.click();
    expect(dialog.hasAttribute("open")).toBe(false);
  });

  it("no share button in the disabled (no-sources) state", () => {
    const player = mountPlayer(makePayload({ sources: [] }));
    expect(player.querySelector(".cast-player__share")).toBeNull();
  });
});

describe("cast-audio-player ?t= deep link", () => {
  it("seeks to the ?t= seconds on load", () => {
    window.history.replaceState({}, "", "/?t=42");
    const player = mountPlayer(makePayload({ duration: 600 }));
    expect(audioOf(player).currentTime).toBe(42);
    window.history.replaceState({}, "", "/");
  });
});
