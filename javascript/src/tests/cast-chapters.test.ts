import { beforeEach, describe, expect, it } from "vitest";

import "@/audio/custom-player";
import { _clearRegistry } from "@/audio/player-registry";
import type { PlayerPayload } from "@/audio/types";
import { installMediaMock, installSyncRaf } from "./media-mock";

function makePayload(overrides: Partial<PlayerPayload> = {}): PlayerPayload {
  return {
    audioId: 3,
    title: "E",
    subtitle: "",
    duration: 100,
    poster: "",
    sources: [{ type: "audio/mp4", src: "/a.m4a" }],
    chapters: [],
    transcript: { cues: [] },
    ...overrides,
  };
}

function mount(payload: PlayerPayload, mode = "list") {
  const script = document.createElement("script");
  script.type = "application/json";
  script.id = "cast-player-data-3";
  script.textContent = JSON.stringify(payload);
  document.body.appendChild(script);

  const player = document.createElement("cast-audio-player");
  player.id = "cast-player-3";
  player.setAttribute("data-payload", "cast-player-data-3");
  document.body.appendChild(player);

  const chapters = document.createElement("cast-chapters");
  chapters.setAttribute("for", "cast-player-3");
  chapters.setAttribute("data-mode", mode);
  document.body.appendChild(chapters);
  return { player: player as HTMLElement & { controller?: any }, chapters };
}

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

beforeEach(() => {
  document.body.innerHTML = "";
  _clearRegistry();
  installMediaMock();
  installSyncRaf();
  installLocalStorage();
});

describe("cast-chapters", () => {
  const chapters = [
    { start: 0, title: "Intro" },
    { start: 10, title: "Body" },
  ];

  it("renders nothing when there are no chapters", () => {
    const { chapters: el } = mount(makePayload({ chapters: [] }));
    expect(el.children.length).toBe(0);
  });

  it("renders a list of seek buttons", () => {
    const { chapters: el } = mount(makePayload({ chapters }));
    const buttons = el.querySelectorAll(".cast-chapters__button");
    expect(buttons).toHaveLength(2);
    expect(buttons[1].textContent).toContain("Body");
  });

  it("marks the current chapter on chapterchange", () => {
    const { player, chapters: el } = mount(makePayload({ chapters }));
    const audio = player.querySelector("audio") as HTMLAudioElement;
    audio.currentTime = 50;
    audio.dispatchEvent(new Event("timeupdate"));
    const buttons = el.querySelectorAll(".cast-chapters__button");
    expect(buttons[1].getAttribute("aria-current")).toBe("true");
    expect(buttons[0].hasAttribute("aria-current")).toBe(false);
  });

  it("is a collapsed pill by default and expands on toggle (inert when collapsed)", () => {
    const { chapters: el } = mount(makePayload({ chapters }));
    const body = el.querySelector(".cast-panel__body") as HTMLElement;
    const toggle = el.querySelector(".cast-panel__toggle") as HTMLButtonElement;
    // Collapsed by default: body inert, not open.
    expect(body.hasAttribute("inert")).toBe(true);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(el.querySelector(".cast-panel.is-open")).toBeNull();
    // Expands on click.
    toggle.click();
    expect(body.hasAttribute("inert")).toBe(false);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    // The count lives in the body (constant-width toggle), not on the pill.
    expect(toggle.querySelector(".cast-panel__count")).toBeNull();
    expect(body.querySelector(".cast-panel__count")?.textContent).toContain("chapters");
  });

  it("seeks on activation", () => {
    const { player, chapters: el } = mount(makePayload({ chapters }));
    const audio = player.querySelector("audio") as HTMLAudioElement;
    (el.querySelectorAll(".cast-chapters__button")[1] as HTMLButtonElement).click();
    expect(audio.currentTime).toBe(10);
  });

  it("renders a compact current indicator in current mode", () => {
    const { player, chapters: el } = mount(makePayload({ chapters }), "current");
    expect(el.querySelector(".cast-chapters__list")).toBeNull();
    const current = el.querySelector(".cast-chapters__current") as HTMLElement;
    const audio = player.querySelector("audio") as HTMLAudioElement;
    audio.currentTime = 50;
    audio.dispatchEvent(new Event("timeupdate"));
    expect(current.textContent).toBe("Body");
  });
});
