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

function openPanel(transcript: HTMLElement): void {
  (transcript.querySelector(".cast-panel__toggle") as HTMLButtonElement).click();
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

  it("renders a timestamp and speaker label per cue", () => {
    const { transcript } = mount(makePayload());
    const cue = transcript.querySelector(".cast-transcript__cue") as HTMLElement;
    expect(cue.querySelector(".cast-transcript__time")?.textContent).toBe("0:00");
    expect(cue.querySelector(".cast-transcript__speaker")?.textContent).toBe("Alice");
  });

  it("repeats the speaker label only on speaker change", () => {
    const cues: Cue[] = [
      { start: 0, end: 1, speaker: "Alice", text: "one" },
      { start: 1, end: 2, speaker: "Alice", text: "two" },
      { start: 2, end: 3, speaker: "Bob", text: "three" },
    ];
    const { transcript } = mount(makePayload({ transcript: { cues } }));
    const speakers = transcript.querySelectorAll(".cast-transcript__speaker");
    expect(Array.from(speakers).map((s) => s.textContent)).toEqual(["Alice", "Bob"]);
  });

  it("renders nothing when there is no transcript (null)", () => {
    const { transcript } = mount(makePayload({ transcript: null }));
    expect(transcript.querySelector(".cast-transcript")).toBeNull();
  });

  it("renders nothing when the transcript is loaded but empty", () => {
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

  it("is collapsed by default and toggles open", () => {
    const { transcript } = mount(makePayload());
    const section = transcript.querySelector(".cast-transcript") as HTMLElement;
    expect(section.classList.contains("is-open")).toBe(false);
    openPanel(transcript);
    expect(section.classList.contains("is-open")).toBe(true);
    expect((transcript.querySelector(".cast-panel__toggle") as HTMLElement).getAttribute("aria-expanded")).toBe(
      "true",
    );
  });

  it("marks the collapsed panel inert so cues leave the tab order", () => {
    const { transcript } = mount(makePayload());
    const body = transcript.querySelector(".cast-panel__body") as HTMLElement;
    expect(body.hasAttribute("inert")).toBe(true); // collapsed by default
    openPanel(transcript);
    expect(body.hasAttribute("inert")).toBe(false);
  });
});

describe("cast-transcript highlight + follow", () => {
  it("marks the current cue with aria-current on cuechange (no aria-live region)", () => {
    const { player, transcript } = mount(makePayload());
    const audio = player.querySelector("audio") as HTMLAudioElement;
    audio.currentTime = 3;
    audio.dispatchEvent(new Event("timeupdate"));
    const cues = transcript.querySelectorAll(".cast-transcript__cue");
    expect(cues[1].getAttribute("aria-current")).toBe("true");
    expect(cues[1].classList.contains("is-current")).toBe(true);
    expect(transcript.querySelector(".cast-transcript__cues")?.hasAttribute("aria-live")).toBe(false);
  });

  it("follow auto-scrolls the current cue when the panel is open", () => {
    const { player, transcript } = mount(makePayload());
    openPanel(transcript);
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    const audio = player.querySelector("audio") as HTMLAudioElement;
    audio.currentTime = 3;
    audio.dispatchEvent(new Event("timeupdate"));
    expect(scroll).toHaveBeenCalledWith(expect.objectContaining({ behavior: "smooth" }));
  });

  it("does not auto-scroll when Follow is off", () => {
    const { player, transcript } = mount(makePayload());
    openPanel(transcript);
    const follow = transcript.querySelector(".cast-transcript__follow") as HTMLButtonElement;
    expect(follow.getAttribute("aria-pressed")).toBe("true");
    follow.click();
    expect(follow.getAttribute("aria-pressed")).toBe("false");
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    const audio = player.querySelector("audio") as HTMLAudioElement;
    audio.currentTime = 3;
    audio.dispatchEvent(new Event("timeupdate"));
    expect(scroll).not.toHaveBeenCalled();
  });

  it("respects reduced-motion (auto behavior)", () => {
    window.matchMedia = vi.fn().mockReturnValue({ matches: true }) as unknown as typeof window.matchMedia;
    const { player, transcript } = mount(makePayload());
    openPanel(transcript);
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    const audio = player.querySelector("audio") as HTMLAudioElement;
    audio.currentTime = 3;
    audio.dispatchEvent(new Event("timeupdate"));
    expect(scroll).toHaveBeenCalledWith(expect.objectContaining({ behavior: "auto" }));
  });
});

describe("cast-transcript search", () => {
  function searchInput(transcript: HTMLElement): HTMLInputElement {
    return transcript.querySelector(".cast-transcript__search-input") as HTMLInputElement;
  }

  it("marks matches via DOM splitting, case-insensitive, text-only", () => {
    const { transcript } = mount(makePayload());
    openPanel(transcript);
    const input = searchInput(transcript);
    input.value = "WORLD";
    input.dispatchEvent(new Event("input"));
    const marks = transcript.querySelectorAll("mark");
    expect(marks).toHaveLength(2);
    expect(marks[0].textContent).toBe("world");
    input.value = "Alice"; // speaker labels are not searched
    input.dispatchEvent(new Event("input"));
    expect(transcript.querySelectorAll("mark")).toHaveLength(0);
  });

  it("announces the match count and highlights the first match", () => {
    const { transcript } = mount(makePayload());
    openPanel(transcript);
    const input = searchInput(transcript);
    input.value = "world";
    input.dispatchEvent(new Event("input"));
    const status = transcript.querySelector(".cast-transcript__search-status") as HTMLElement;
    expect(status.getAttribute("aria-live")).toBe("polite");
    expect(status.textContent).toBe("2 matches");
    // the first match is made the active match (visible) automatically
    expect(transcript.querySelectorAll("mark.is-active-match")).toHaveLength(1);
  });

  it("next/prev wrap and move the active match without seeking", () => {
    const { player, transcript } = mount(makePayload());
    openPanel(transcript);
    const audio = player.querySelector("audio") as HTMLAudioElement;
    audio.currentTime = 99;
    const input = searchInput(transcript);
    input.value = "world";
    input.dispatchEvent(new Event("input"));
    const next = transcript.querySelector(".cast-transcript__nav[aria-label='Next match']") as HTMLButtonElement;
    next.click();
    next.click(); // wraps back to first
    expect(transcript.querySelectorAll("mark.is-active-match")).toHaveLength(1);
    expect(audio.currentTime).toBe(99);
  });

  it("keeps focus in the search input while typing (auto-jump does not steal focus)", () => {
    const { transcript } = mount(makePayload());
    openPanel(transcript);
    const input = searchInput(transcript);
    input.focus();
    input.value = "world";
    input.dispatchEvent(new Event("input"));
    expect(document.activeElement).toBe(input);
  });

  it("clears marks when the query is emptied", () => {
    const { transcript } = mount(makePayload());
    openPanel(transcript);
    const input = searchInput(transcript);
    input.value = "world";
    input.dispatchEvent(new Event("input"));
    input.value = "";
    input.dispatchEvent(new Event("input"));
    expect(transcript.querySelectorAll("mark")).toHaveLength(0);
  });
});

describe("cast-transcript keyboard-navigable toggle", () => {
  function tabbableToggle(transcript: HTMLElement): HTMLInputElement {
    return transcript.querySelector(".cast-transcript__options input[type='checkbox']") as HTMLInputElement;
  }

  it("flips tabindex and persists the preference", () => {
    const { transcript } = mount(makePayload());
    const toggle = tabbableToggle(transcript);
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

describe("cast-transcript lazy fallback path", () => {
  const okFetch = () =>
    vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ cues: CUES }),
      }),
    );

  it("does not fetch on mount while collapsed; fetches once on first open", async () => {
    const fetchMock = okFetch();
    vi.stubGlobal("fetch", fetchMock);
    const { transcript } = mount(makePayload({ transcript: { url: "/api/audios/5/player-transcript/" } }));
    // The button/panel renders, but nothing is fetched and no loading shows yet.
    expect(transcript.querySelector(".cast-transcript")).not.toBeNull();
    expect(transcript.querySelector(".cast-transcript__loading")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
    // First open triggers exactly one fetch and shows the loading state.
    openPanel(transcript);
    expect(transcript.querySelector(".cast-transcript__loading")).not.toBeNull();
    await vi.waitFor(() => expect(transcript.querySelectorAll(".cast-transcript__cue").length).toBe(3));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    // Closing and reopening does not refetch.
    openPanel(transcript); // close
    openPanel(transcript); // open again
    expect(fetchMock).toHaveBeenCalledTimes(1);
    vi.unstubAllGlobals();
  });

  it("the transcript element never fetches itself (the player owns fetching)", async () => {
    const fetchMock = okFetch();
    vi.stubGlobal("fetch", fetchMock);
    // Mount the transcript WITHOUT a player; opening cannot resolve a controller,
    // so no fetch can originate from the transcript element.
    const script = document.createElement("script");
    script.type = "application/json";
    script.id = "cast-player-data-5";
    script.textContent = JSON.stringify(makePayload({ transcript: { url: "/x" } }));
    document.body.appendChild(script);
    const transcript = document.createElement("cast-transcript");
    transcript.setAttribute("for", "cast-player-5");
    document.body.appendChild(transcript);
    // No controller resolved -> the element rendered nothing and cannot fetch.
    expect(fetchMock).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("shows 'unavailable' on a failed fetch and retries on a later open", async () => {
    const fetchMock = vi.fn(() => Promise.resolve({ ok: false }));
    vi.stubGlobal("fetch", fetchMock as unknown as typeof fetch);
    const { transcript } = mount(makePayload({ transcript: { url: "/api/audios/5/player-transcript/" } }));
    openPanel(transcript);
    await vi.waitFor(() =>
      expect(transcript.querySelector(".cast-transcript__loading")?.textContent).toContain("unavailable"),
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
    // A later open retries (transcriptFailed cleared loading without marking loaded).
    fetchMock.mockImplementation(() => Promise.resolve({ ok: true, json: () => Promise.resolve({ cues: CUES }) }));
    openPanel(transcript); // close
    openPanel(transcript); // open -> retry
    await vi.waitFor(() => expect(transcript.querySelectorAll(".cast-transcript__cue").length).toBe(3));
    expect(fetchMock).toHaveBeenCalledTimes(2);
    vi.unstubAllGlobals();
  });

  it("a persisted-open panel loads on connect without a click", async () => {
    window.localStorage.setItem("cast-transcript-open", "true");
    const fetchMock = okFetch();
    vi.stubGlobal("fetch", fetchMock);
    const { transcript } = mount(makePayload({ transcript: { url: "/api/audios/5/player-transcript/" } }));
    await vi.waitFor(() => expect(transcript.querySelectorAll(".cast-transcript__cue").length).toBe(3));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    vi.unstubAllGlobals();
  });
});

describe("cast-transcript late wiring", () => {
  it("resolves a controller that connects after the transcript (cast:player-ready)", () => {
    const { transcript } = mount(makePayload(), { transcriptFirst: true });
    expect(transcript.querySelectorAll(".cast-transcript__cue")).toHaveLength(3);
  });
});
