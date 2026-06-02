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

beforeEach(() => {
  document.body.innerHTML = "";
  _clearRegistry();
  installMediaMock();
  installSyncRaf();
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
