import { beforeEach, describe, expect, it } from "vitest";

import "@/audio/custom-player";
import { _clearRegistry, getController } from "@/audio/player-registry";
import type { PlayerPayload } from "@/audio/types";
import { installMediaMock, installSyncRaf } from "./media-mock";

function payload(audioId: number): PlayerPayload {
  return {
    audioId,
    title: "E",
    subtitle: "",
    duration: 100,
    poster: "",
    sources: [{ type: "audio/mp4", src: "/a.m4a" }],
    chapters: [],
    transcript: { cues: [{ start: 0, end: 1, speaker: "", text: `cue-${audioId}` }] },
  };
}

function mount(audioId: number) {
  const script = document.createElement("script");
  script.type = "application/json";
  script.id = `cast-player-data-${audioId}`;
  script.textContent = JSON.stringify(payload(audioId));
  document.body.appendChild(script);

  const player = document.createElement("cast-audio-player");
  player.id = `cast-player-${audioId}`;
  player.setAttribute("data-payload", `cast-player-data-${audioId}`);
  document.body.appendChild(player);
  return player as HTMLElement & { controller?: any };
}

beforeEach(() => {
  document.body.innerHTML = "";
  _clearRegistry();
  installMediaMock();
  installSyncRaf();
});

describe("multi-instance wiring", () => {
  it("keeps two players independent and cleans up after one disconnects (htmx swap)", () => {
    const a = mount(1);
    const b = mount(2);
    expect(getController("cast-player-1")).toBe(a.controller);
    expect(getController("cast-player-2")).toBe(b.controller);

    const audioA = a.querySelector("audio") as HTMLAudioElement;
    const audioB = b.querySelector("audio") as HTMLAudioElement;
    audioA.currentTime = 50;
    audioA.dispatchEvent(new Event("timeupdate"));
    // b is unaffected by a's playback
    expect(b.controller.currentTime).toBe(0);

    a.remove();
    expect(getController("cast-player-1")).toBeUndefined();
    expect(getController("cast-player-2")).toBe(b.controller);
    // b still works after the swap
    audioB.currentTime = 10;
    audioB.dispatchEvent(new Event("timeupdate"));
    expect(b.controller.currentTime).toBe(10);
  });
});
