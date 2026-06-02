import { beforeEach, describe, expect, it, vi } from "vitest";

import "@/audio/custom-player";
import { _clearRegistry } from "@/audio/player-registry";
import type { Cue, PlayerPayload } from "@/audio/types";
import { installMediaMock, installSyncRaf } from "./media-mock";

const CUES: Cue[] = [
  { start: 0, end: 2, speaker: "Alice", text: "hello world" },
  { start: 2, end: 4, speaker: "Bob", text: "goodbye world" },
  { start: 4, end: 6, speaker: "Alice", text: "another line" },
];

function makePayload(overrides: Partial<PlayerPayload> = {}): PlayerPayload {
  return {
    audioId: 5,
    title: "E",
    subtitle: "",
    duration: 100,
    poster: "",
    sources: [{ type: "audio/mp4", src: "/a.m4a" }],
    chapters: [],
    transcript: { cues: CUES },
    ...overrides,
  };
}

function mount(payload: PlayerPayload, { transcriptFirst = false } = {}) {
  const script = document.createElement("script");
  script.type = "application/json";
  script.id = "cast-player-data-5";
  script.textContent = JSON.stringify(payload);
  document.body.appendChild(script);

  const player = document.createElement("cast-audio-player");
  player.id = "cast-player-5";
  player.setAttribute("data-payload", "cast-player-data-5");

  const transcript = document.createElement("cast-transcript");
  transcript.setAttribute("for", "cast-player-5");

  if (transcriptFirst) {
    document.body.appendChild(transcript);
    document.body.appendChild(player);
  } else {
    document.body.appendChild(player);
    document.body.appendChild(transcript);
  }
  return { player: player as HTMLElement & { controller?: any }, transcript };
}

beforeEach(() => {
  document.body.innerHTML = "";
  _clearRegistry();
  installMediaMock();
  installSyncRaf();
  Element.prototype.scrollIntoView = vi.fn();
  window.matchMedia = vi.fn().mockReturnValue({ matches: false }) as unknown as typeof window.matchMedia;
  installLocalStorage();
});

function installLocalStorage(): void {
  const store = new Map<string, string>();
  const mock: Storage = {
    get length() {
      return store.size;
    },
    clear: () => store.clear(),
    getItem: (key: string) => (store.has(key) ? store.get(key)! : null),
    key: (index: number) => Array.from(store.keys())[index] ?? null,
    removeItem: (key: string) => store.delete(key),
    setItem: (key: string, value: string) => store.set(key, String(value)),
  };
  Object.defineProperty(window, "localStorage", { configurable: true, value: mock });
}

describe("cast-transcript rendering", () => {
  it("renders cues with textContent only (XSS-safe)", () => {
    const payload = makePayload({
      transcript: { cues: [{ start: 0, end: 1, speaker: "X", text: "<script>alert(1)</script>" }] },
    });
    const { transcript } = mount(payload);
    const cue = transcript.querySelector(".cast-transcript__cue") as HTMLElement;
    expect(cue.querySelector("script")).toBeNull();
    expect(cue.textContent).toContain("<script>alert(1)</script>");
  });

  it("renders speaker labels in a separate span", () => {
    const { transcript } = mount(makePayload());
    const speaker = transcript.querySelector(".cast-transcript__speaker") as HTMLElement;
    expect(speaker.textContent).toBe("Alice");
  });

  it("renders nothing when there is no transcript", () => {
    const { transcript } = mount(makePayload({ transcript: { cues: [] } }));
    expect(transcript.querySelector(".cast-transcript")).toBeNull();
  });

  it("cue buttons are not tabbable by default", () => {
    const { transcript } = mount(makePayload());
    const cue = transcript.querySelector(".cast-transcript__cue") as HTMLButtonElement;
    expect(cue.tabIndex).toBe(-1);
  });

  it("seeks on cue activation", () => {
    const { player, transcript } = mount(makePayload());
    const audio = player.querySelector("audio") as HTMLAudioElement;
    (transcript.querySelectorAll(".cast-transcript__cue")[1] as HTMLButtonElement).click();
    expect(audio.currentTime).toBeCloseTo(2.01);
  });
});

describe("cast-transcript highlight + auto-scroll", () => {
  it("marks the current cue with aria-current on cuechange (no aria-live region)", () => {
    const { player, transcript } = mount(makePayload());
    const audio = player.querySelector("audio") as HTMLAudioElement;
    audio.currentTime = 3;
    audio.dispatchEvent(new Event("timeupdate"));
    const cues = transcript.querySelectorAll(".cast-transcript__cue");
    expect(cues[1].getAttribute("aria-current")).toBe("true");
    expect(transcript.querySelector(".cast-transcript__cues")?.hasAttribute("aria-live")).toBe(false);
  });

  it("auto-scrolls the current cue into view, smoothly unless reduced-motion", () => {
    const scroll = vi.spyOn(Element.prototype, "scrollIntoView");
    const { player } = mount(makePayload());
    const audio = player.querySelector("audio") as HTMLAudioElement;
    audio.currentTime = 3;
    audio.dispatchEvent(new Event("timeupdate"));
    expect(scroll).toHaveBeenCalledWith(expect.objectContaining({ behavior: "smooth" }));
  });

  it("respects reduced-motion (auto behavior)", () => {
    window.matchMedia = vi.fn().mockReturnValue({ matches: true }) as unknown as typeof window.matchMedia;
    const scroll = vi.spyOn(Element.prototype, "scrollIntoView");
    const { player } = mount(makePayload());
    const audio = player.querySelector("audio") as HTMLAudioElement;
    audio.currentTime = 3;
    audio.dispatchEvent(new Event("timeupdate"));
    expect(scroll).toHaveBeenCalledWith(expect.objectContaining({ behavior: "auto" }));
  });

  it("does not auto-scroll when the toggle is off", () => {
    const { player, transcript } = mount(makePayload());
    const toggle = Array.from(transcript.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')).find((i) =>
      i.parentElement?.textContent?.includes("Auto-scroll"),
    )!;
    expect(toggle.parentElement?.textContent).toContain("Auto-scroll");
    toggle.checked = false;
    toggle.dispatchEvent(new Event("change"));
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    const audio = player.querySelector("audio") as HTMLAudioElement;
    audio.currentTime = 3;
    audio.dispatchEvent(new Event("timeupdate"));
    expect(scroll).not.toHaveBeenCalled();
  });
});

describe("cast-transcript search", () => {
  function searchInput(transcript: HTMLElement): HTMLInputElement {
    return transcript.querySelector(".cast-transcript__search-input") as HTMLInputElement;
  }

  it("marks matches via DOM splitting, case-insensitive, text-only", () => {
    const { transcript } = mount(makePayload());
    const input = searchInput(transcript);
    input.value = "WORLD";
    input.dispatchEvent(new Event("input"));
    const marks = transcript.querySelectorAll("mark");
    expect(marks).toHaveLength(2); // "hello world", "goodbye world"
    expect(marks[0].textContent).toBe("world");
    // speaker labels are not searched
    input.value = "Alice";
    input.dispatchEvent(new Event("input"));
    expect(transcript.querySelectorAll("mark")).toHaveLength(0);
  });

  it("announces the match count via a status region", () => {
    const { transcript } = mount(makePayload());
    const input = searchInput(transcript);
    input.value = "world";
    input.dispatchEvent(new Event("input"));
    const status = transcript.querySelector(".cast-transcript__search-status") as HTMLElement;
    expect(status.getAttribute("aria-live")).toBe("polite");
    expect(status.textContent).toBe("2 matches");
  });

  it("next/prev scroll+focus+wrap without seeking", () => {
    const { player, transcript } = mount(makePayload());
    const audio = player.querySelector("audio") as HTMLAudioElement;
    audio.currentTime = 99;
    const input = searchInput(transcript);
    input.value = "world";
    input.dispatchEvent(new Event("input"));
    const next = transcript.querySelector(".cast-transcript__match-next") as HTMLButtonElement;
    const focus = vi.spyOn(HTMLElement.prototype, "focus");
    next.click(); // first match
    next.click(); // second match
    next.click(); // wraps to first
    expect(focus).toHaveBeenCalled();
    expect(audio.currentTime).toBe(99); // never seeked
  });

  it("clears marks when the query is emptied", () => {
    const { transcript } = mount(makePayload());
    const input = searchInput(transcript);
    input.value = "world";
    input.dispatchEvent(new Event("input"));
    input.value = "";
    input.dispatchEvent(new Event("input"));
    expect(transcript.querySelectorAll("mark")).toHaveLength(0);
  });
});

describe("cast-transcript keyboard-navigable toggle", () => {
  it("flips tabindex and persists the preference", () => {
    const { transcript } = mount(makePayload());
    const toggle = Array.from(transcript.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')).find((i) =>
      i.parentElement?.textContent?.includes("Keyboard-navigable"),
    )!;
    toggle.checked = true;
    toggle.dispatchEvent(new Event("change"));
    const cue = transcript.querySelector(".cast-transcript__cue") as HTMLButtonElement;
    expect(cue.tabIndex).toBe(0);
    expect(window.localStorage.getItem("cast-transcript-tabbable")).toBe("true");
  });

  it("restores tabbable cues from a persisted preference", () => {
    window.localStorage.setItem("cast-transcript-tabbable", "true");
    const { transcript } = mount(makePayload());
    const cue = transcript.querySelector(".cast-transcript__cue") as HTMLButtonElement;
    expect(cue.tabIndex).toBe(0);
  });
});

describe("cast-transcript fallback path", () => {
  it("shows loading then populates via setCues, and never fetches itself", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ cues: CUES }),
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { player, transcript } = mount(makePayload({ transcript: { url: "/api/audios/5/player-transcript/" } }));
    expect(transcript.querySelector(".cast-transcript__loading")).not.toBeNull();
    await vi.waitFor(() => expect(transcript.querySelectorAll(".cast-transcript__cue").length).toBe(3));
    // only the player fetched, exactly once; the transcript never fetches
    expect(fetchMock).toHaveBeenCalledTimes(1);
    void player;
    vi.unstubAllGlobals();
  });
});

describe("cast-transcript late wiring", () => {
  it("resolves a controller that connects after the transcript (cast:player-ready)", () => {
    const { transcript } = mount(makePayload(), { transcriptFirst: true });
    expect(transcript.querySelectorAll(".cast-transcript__cue")).toHaveLength(3);
  });
});
