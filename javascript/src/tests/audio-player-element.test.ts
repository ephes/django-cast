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

  it("range input calls seek and shows elapsed + remaining, with no aria-live on time", () => {
    const player = mountPlayer(makePayload({ duration: 75 }));
    const range = player.querySelector(".cast-player__seek") as HTMLInputElement;
    const elapsed = player.querySelector(".cast-player__time") as HTMLOutputElement;
    const remaining = player.querySelector(".cast-player__remaining") as HTMLOutputElement;
    expect(range.max).toBe("75");
    expect(elapsed.hasAttribute("aria-live")).toBe(false);
    expect(remaining.hasAttribute("aria-live")).toBe(false);
    range.value = "65";
    range.dispatchEvent(new Event("input"));
    expect(audioOf(player).currentTime).toBe(65);
    expect(elapsed.textContent).toBe("1:05");
    expect(remaining.textContent).toBe("-0:10");
    expect(range.getAttribute("aria-valuetext")).toContain("of");
  });

  it("formats hours as h:mm:ss for elapsed and remaining", () => {
    const player = mountPlayer(makePayload({ duration: 3725 }));
    const elapsed = player.querySelector(".cast-player__time") as HTMLOutputElement;
    const remaining = player.querySelector(".cast-player__remaining") as HTMLOutputElement;
    expect(elapsed.textContent).toBe("0:00");
    expect(remaining.textContent).toBe("-1:02:05");
  });

  it("duration-unknown disables the range and shows --:-- remaining, then fills on durationchange", () => {
    const player = mountPlayer(makePayload({ duration: null }));
    const range = player.querySelector(".cast-player__seek") as HTMLInputElement;
    const elapsed = player.querySelector(".cast-player__time") as HTMLOutputElement;
    const remaining = player.querySelector(".cast-player__remaining") as HTMLOutputElement;
    expect(range.disabled).toBe(true);
    expect(range.max).toBe("0");
    expect(range.getAttribute("aria-valuetext")).toBe("duration unknown");
    expect(elapsed.textContent).toBe("0:00");
    expect(remaining.textContent).toBe("--:--");

    const audio = audioOf(player);
    audio.duration = 90;
    audio.dispatchEvent(new Event("durationchange"));
    expect(range.disabled).toBe(false);
    expect(range.max).toBe("90");
    expect(remaining.textContent).toBe("-1:30");
  });

  it("clamps remaining time to zero past the end", () => {
    const player = mountPlayer(makePayload({ duration: 75 }));
    const audio = audioOf(player);
    audio.currentTime = 80; // past the end
    audio.dispatchEvent(new Event("timeupdate"));
    const remaining = player.querySelector(".cast-player__remaining") as HTMLOutputElement;
    expect(remaining.textContent).toBe("-0:00");
  });

  it("does not hijack Space from interactive controls (e.g. the share button)", () => {
    const player = mountPlayer(makePayload({ duration: 100 }));
    const play = player.querySelector(".cast-player__play") as HTMLButtonElement;
    const share = player.querySelector(".cast-player__share") as HTMLButtonElement;
    expect(play.getAttribute("aria-label")).toBe("Play");
    // Space originating from the share button must NOT toggle playback (it should
    // activate the button natively) — so the play state stays unchanged.
    share.dispatchEvent(new KeyboardEvent("keydown", { key: " ", bubbles: true }));
    expect(play.getAttribute("aria-label")).toBe("Play");
  });

  it("renders a keyboard-shortcuts button with a popover (not a raw <details>)", () => {
    const player = mountPlayer(makePayload());
    const button = player.querySelector(".cast-player__shortcuts-btn") as HTMLButtonElement;
    expect(button).not.toBeNull();
    expect(button.getAttribute("aria-label")).toBe("Keyboard shortcuts");
    const popover = player.querySelector("#" + button.getAttribute("popovertarget")) as HTMLElement;
    expect(popover).not.toBeNull();
    expect(popover.hasAttribute("popover")).toBe(true);
    expect(popover.textContent).toContain("play / pause");
    expect(player.querySelector("details.cast-player__shortcuts")).toBeNull();
  });

  it("no-sources renders a disabled state with an unavailable message", () => {
    const player = mountPlayer(makePayload({ sources: [] }));
    const button = player.querySelector(".cast-player__play") as HTMLButtonElement;
    const range = player.querySelector(".cast-player__seek") as HTMLInputElement;
    expect(button.disabled).toBe(true);
    expect(range.disabled).toBe(true);
    expect(player.querySelector(".cast-player__unavailable")).not.toBeNull();
  });

  it("keyboard shortcuts toggle and seek when the player has focus", () => {
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

  it("keyboard shortcuts are page-global: a keydown on the body acts on the player", () => {
    const player = mountPlayer(makePayload({ duration: 100 }));
    const audio = audioOf(player);
    const button = player.querySelector(".cast-player__play") as HTMLButtonElement;
    // Focus is NOT on the player (it sits on the body) — the reader is scrolling
    // the transcript. The shortcut must still act on the only/active player.
    audio.currentTime = 30;
    document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    expect(audio.currentTime).toBe(35);
    document.body.dispatchEvent(new KeyboardEvent("keydown", { key: " ", bubbles: true }));
    expect(button.getAttribute("aria-label")).toBe("Pause");
  });

  it("multiple players: global shortcuts stay inert until one is engaged, then route to it", () => {
    const a = mountPlayer(makePayload({ audioId: 7, duration: 100 }), "cast-player-a");
    const b = mountPlayer(makePayload({ audioId: 8, duration: 100 }), "cast-player-b");
    const audioA = audioOf(a);
    const audioB = audioOf(b);
    audioA.currentTime = 10;
    audioB.currentTime = 20;
    // No player engaged yet: a body keypress is ambiguous and must move neither.
    document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    expect(audioA.currentTime).toBe(10);
    expect(audioB.currentTime).toBe(20);
    // Engaging player B (clicking its play) makes it the page-global target.
    (b.querySelector(".cast-player__play") as HTMLButtonElement).click();
    document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    expect(audioA.currentTime).toBe(10);
    expect(audioB.currentTime).toBe(25);
  });

  it("multiple players: a keyboard shortcut on one player makes it the page-global target", () => {
    const a = mountPlayer(makePayload({ audioId: 7, duration: 100 }), "cast-player-a");
    const b = mountPlayer(makePayload({ audioId: 8, duration: 100 }), "cast-player-b");
    const audioA = audioOf(a);
    const audioB = audioOf(b);
    audioA.currentTime = 10;
    audioB.currentTime = 50;
    // A shortcut delivered to player A specifically (focus inside A) engages it.
    a.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    expect(audioA.currentTime).toBe(15);
    // A later body keypress now targets A, the last engaged player — not B.
    document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    expect(audioA.currentTime).toBe(20);
    expect(audioB.currentTime).toBe(50);
  });

  it("multiple players: a transcript/chapter navigation (even while playing) makes it the global target", () => {
    const a = mountPlayer(makePayload({ audioId: 7, duration: 100 }), "cast-player-a");
    const b = mountPlayer(
      makePayload({
        audioId: 8,
        duration: 100,
        transcript: { cues: [{ start: 60, end: 65, speaker: "", text: "x" }] },
      }),
      "cast-player-b",
    );
    const audioA = audioOf(a);
    const audioB = audioOf(b);
    // Engage A first so it is the active player.
    (a.querySelector(".cast-player__play") as HTMLButtonElement).click();
    audioA.currentTime = 10;
    // Navigate a cue in B (what a transcript-line click does via seekToCue).
    // Even with no "play" event — B may already be playing — this hands the
    // page-global target to B.
    b.controller?.seekToCue(0);
    document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    expect(audioB.currentTime).toBeCloseTo(65.01); // 60 + epsilon, then +5
    expect(audioA.currentTime).toBe(10);
  });

  it("multiple players: a low-level seek (the initial ?t= deep-link) does NOT mark a player active", () => {
    const a = mountPlayer(makePayload({ audioId: 7, duration: 100 }), "cast-player-a");
    const b = mountPlayer(makePayload({ audioId: 8, duration: 100 }), "cast-player-b");
    const audioA = audioOf(a);
    const audioB = audioOf(b);
    audioA.currentTime = 10;
    audioB.currentTime = 50;
    // applyStartAt() seeks via the low-level seek() during page setup; that must
    // not count as engagement, so with two players and none engaged a body
    // keypress stays inert rather than acting on whichever player deep-linked.
    b.controller?.seek(70);
    document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    expect(audioA.currentTime).toBe(10);
    expect(audioB.currentTime).toBe(70); // only the deep-link seek, no shortcut
  });

  it("does not hijack modified shortcut keys (browser/OS navigation)", () => {
    const player = mountPlayer(makePayload({ duration: 100 }));
    const audio = audioOf(player);
    audio.currentTime = 50;
    // Cmd/Ctrl/Alt/Shift + an arrow is a browser/OS nav chord — leave it alone.
    const event = new KeyboardEvent("keydown", {
      key: "ArrowLeft",
      metaKey: true,
      bubbles: true,
      cancelable: true,
    });
    document.body.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
    expect(audio.currentTime).toBe(50);
  });

  it("does not hijack keys while typing in a page input outside the player", () => {
    const player = mountPlayer(makePayload({ duration: 100 }));
    const audio = audioOf(player);
    audio.currentTime = 40;
    const input = document.createElement("input");
    document.body.appendChild(input);
    const event = new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true, cancelable: true });
    input.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
    expect(audio.currentTime).toBe(40);
  });

  it("is focusable and the play button moves focus to it so shortcuts are reachable", () => {
    const player = mountPlayer(makePayload({ duration: 100 }));
    expect(player.tabIndex).toBe(0);
    expect(player.getAttribute("aria-keyshortcuts")).toContain("Space");
    const play = player.querySelector(".cast-player__play") as HTMLButtonElement;
    play.click();
    expect(document.activeElement).toBe(player);
    // With the player focused, a player shortcut now acts on it.
    const audio = audioOf(player);
    audio.currentTime = 10;
    player.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    expect(audio.currentTime).toBe(15);
  });

  it("does not make the disabled (no-sources) player focusable", () => {
    const player = mountPlayer(makePayload({ sources: [] }));
    expect(player.hasAttribute("tabindex")).toBe(false);
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

describe("cast-audio-player lazy transcript hydration", () => {
  it("does not fetch on connect; fetches once when requestTranscript() is called", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ cues: [{ start: 0, end: 1, speaker: "", text: "late" }] }),
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const player = mountPlayer(makePayload({ transcript: { url: "/api/audios/7/player-transcript/" } }));
    // No eager fetch on connect (revision 4).
    expect(fetchMock).not.toHaveBeenCalled();
    expect(player.controller?.hasTranscript).toBe(true);
    expect(player.controller?.transcriptLoaded).toBe(false);
    // The player is the sole fetcher; it fetches exactly once when asked.
    player.controller?.requestTranscript();
    await vi.waitFor(() => expect(player.controller?.getCues().length).toBe(1));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(player.controller?.transcriptLoaded).toBe(true);
    vi.unstubAllGlobals();
  });

  it("calls transcriptFailed (no cues, retry allowed) when the fetch is not ok", async () => {
    const fetchMock = vi.fn(() => Promise.resolve({ ok: false }));
    vi.stubGlobal("fetch", fetchMock as unknown as typeof fetch);
    const player = mountPlayer(makePayload({ transcript: { url: "/api/audios/7/player-transcript/" } }));
    const errors: string[] = [];
    player.controller?.addEventListener("transcripterror", () => errors.push("err"));
    player.controller?.requestTranscript();
    await vi.waitFor(() => expect(errors).toEqual(["err"]));
    expect(player.controller?.transcriptLoaded).toBe(false);
    expect(player.controller?.transcriptLoading).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(1);
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

describe("cast-audio-player transport-share opt-out", () => {
  function mountWithShare(share: string | null) {
    const payload = makePayload({ duration: 600 });
    const dataId = `cast-player-data-${payload.audioId}`;
    const script = document.createElement("script");
    script.type = "application/json";
    script.id = dataId;
    script.textContent = JSON.stringify(payload);
    document.body.appendChild(script);
    const player = document.createElement("cast-audio-player");
    player.id = "cast-player-7";
    player.setAttribute("data-payload", dataId);
    if (share !== null) {
      player.setAttribute("data-share", share);
    }
    document.body.appendChild(player);
    return player as HTMLElement & {
      getShareState(): { currentTime: number; duration: number | null; audioId: number };
    };
  }

  it('suppresses the in-transport share button and dialog when data-share="none"', () => {
    const player = mountWithShare("none");
    expect(player.querySelector(".cast-player__share")).toBeNull();
    expect(player.querySelector("dialog.cast-share")).toBeNull();
    // The other transport affordances still render.
    expect(player.querySelector(".cast-player__play")).not.toBeNull();
    expect(player.querySelector(".cast-player__shortcuts-btn")).not.toBeNull();
  });

  it("keeps the read-only getShareState() API working with the button suppressed", () => {
    const player = mountWithShare("none");
    (player.querySelector("audio") as HTMLAudioElement).currentTime = 21;
    expect(player.getShareState()).toEqual({ currentTime: 21, duration: 600, audioId: 7 });
  });

  it("renders the in-transport share button by default (no data-share attribute)", () => {
    const player = mountWithShare(null);
    expect(player.querySelector(".cast-player__share")).not.toBeNull();
    expect(player.querySelector("dialog.cast-share")).not.toBeNull();
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
