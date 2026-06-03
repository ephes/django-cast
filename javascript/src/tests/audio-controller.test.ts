import { beforeEach, describe, expect, it, vi } from "vitest";

import { AudioController } from "@/audio/audio-controller";
import type { Chapter, Cue, PlayerPayload } from "@/audio/types";

class FakeAudio extends EventTarget {
  currentTime = 0;
  duration = NaN;
  paused = true;
  error: MediaError | null = null;
  play = vi.fn(() => {
    this.paused = false;
    this.dispatchEvent(new Event("play"));
    return Promise.resolve();
  });
  pause = vi.fn(() => {
    this.paused = true;
    this.dispatchEvent(new Event("pause"));
  });
  emit(type: string): void {
    this.dispatchEvent(new Event(type));
  }
}

function makePayload(overrides: Partial<PlayerPayload> = {}): PlayerPayload {
  return {
    audioId: 1,
    title: "t",
    subtitle: "s",
    duration: null,
    poster: "",
    sources: [{ type: "audio/mp4", src: "/a.m4a" }],
    chapters: [],
    transcript: { cues: [] },
    ...overrides,
  };
}

function setup(overrides: Partial<PlayerPayload> = {}) {
  const audio = new FakeAudio();
  const controller = new AudioController(audio as unknown as HTMLAudioElement, makePayload(overrides));
  return { audio, controller };
}

// rAF runs synchronously so coalesced timeupdate is deterministic.
beforeEach(() => {
  globalThis.requestAnimationFrame = ((cb: FrameRequestCallback) => {
    cb(0);
    return 0;
  }) as typeof requestAnimationFrame;
  // No reduced motion / matchMedia needed here.
});

const cues: Cue[] = [
  { start: 0, end: 2, speaker: "A", text: "one" },
  { start: 2, end: 4, speaker: "B", text: "two" },
  { start: 4, end: 6, speaker: "A", text: "three" },
];

const chapters: Chapter[] = [
  { start: 0, title: "Intro" },
  { start: 10, title: "Body" },
];

function tick(audio: FakeAudio, t: number): void {
  audio.currentTime = t;
  audio.emit("timeupdate");
}

describe("AudioController transport", () => {
  it("play/pause/toggle drive the media element", () => {
    const { audio, controller } = setup();
    void controller.play();
    expect(audio.play).toHaveBeenCalled();
    controller.pause();
    expect(audio.pause).toHaveBeenCalled();
    audio.paused = true;
    controller.toggle();
    expect(audio.play).toHaveBeenCalledTimes(2);
    audio.paused = false;
    controller.toggle();
    expect(audio.pause).toHaveBeenCalledTimes(2);
  });

  it("swallows AbortError but emits error on real failure", async () => {
    const { audio, controller } = setup();
    const errors: unknown[] = [];
    controller.addEventListener("error", (e) => errors.push((e as CustomEvent).detail.error));
    audio.play = vi.fn(() => Promise.reject(Object.assign(new Error("x"), { name: "AbortError" })));
    await controller.play();
    expect(errors).toHaveLength(0);
    audio.play = vi.fn(() => Promise.reject(new Error("boom")));
    await controller.play();
    expect(errors).toHaveLength(1);
  });

  it("seek clamps to [0, duration]", () => {
    const { audio, controller } = setup({ duration: 100 });
    controller.seek(-5);
    expect(audio.currentTime).toBe(0);
    controller.seek(250);
    expect(audio.currentTime).toBe(100);
    controller.seek(42);
    expect(audio.currentTime).toBe(42);
  });

  it("seek only clamps lower bound when duration unknown", () => {
    const { audio, controller } = setup({ duration: null });
    controller.seek(-5);
    expect(audio.currentTime).toBe(0);
    controller.seek(9999);
    expect(audio.currentTime).toBe(9999);
  });

  it("seekToCue seeks just inside the cue", () => {
    const { audio, controller } = setup({ duration: 100, transcript: { cues } });
    controller.seekToCue(1);
    expect(audio.currentTime).toBeCloseTo(2.01);
  });

  it("durationchange fills a null payload duration", () => {
    const { audio, controller } = setup({ duration: null });
    const seen: Array<number | null> = [];
    controller.addEventListener("durationchange", (e) => seen.push((e as CustomEvent).detail.duration));
    audio.duration = 123;
    audio.emit("durationchange");
    expect(controller.duration).toBe(123);
    expect(seen).toEqual([123]);
  });
});

describe("AudioController cue boundaries", () => {
  it("inclusive start, exclusive end, gap -> -1, overlap -> last wins", () => {
    const overlapping: Cue[] = [
      { start: 0, end: 4, speaker: "", text: "a" },
      { start: 2, end: 4, speaker: "", text: "b" },
    ];
    const { audio, controller } = setup({ duration: 100, transcript: { cues: overlapping } });
    tick(audio, 0);
    expect(controller.currentCueIndex).toBe(0); // inclusive start
    tick(audio, 3);
    expect(controller.currentCueIndex).toBe(1); // overlap: last wins
    tick(audio, 4);
    expect(controller.currentCueIndex).toBe(-1); // exclusive end -> gap
  });

  it("ended keeps the last cue/chapter highlighted", () => {
    const { audio, controller } = setup({ duration: 6, transcript: { cues }, chapters });
    audio.currentTime = 6;
    audio.emit("ended");
    expect(controller.currentCueIndex).toBe(cues.length - 1);
    expect(controller.currentChapterIndex).toBe(chapters.length - 1);
  });

  it("t >= duration snaps to the last cue", () => {
    const { audio, controller } = setup({ duration: 6, transcript: { cues } });
    tick(audio, 6);
    expect(controller.currentCueIndex).toBe(cues.length - 1);
  });

  it("empty cues -> -1", () => {
    const { audio, controller } = setup({ duration: 6 });
    tick(audio, 1);
    expect(controller.currentCueIndex).toBe(-1);
  });
});

describe("AudioController chapter boundaries", () => {
  it("before first chapter -> -1, last extends to end", () => {
    const offset: Chapter[] = [
      { start: 5, title: "One" },
      { start: 10, title: "Two" },
    ];
    const { audio, controller } = setup({ duration: 100, chapters: offset });
    tick(audio, 1);
    expect(controller.currentChapterIndex).toBe(-1);
    tick(audio, 7);
    expect(controller.currentChapterIndex).toBe(0);
    tick(audio, 50);
    expect(controller.currentChapterIndex).toBe(1); // last extends
  });
});

describe("AudioController events", () => {
  it("coalesces timeupdate to one dispatch per frame", () => {
    let raf: FrameRequestCallback | null = null;
    globalThis.requestAnimationFrame = ((cb: FrameRequestCallback) => {
      raf = cb;
      return 1;
    }) as typeof requestAnimationFrame;
    const { audio, controller } = setup({ duration: 100 });
    const updates: number[] = [];
    controller.addEventListener("timeupdate", (e) => updates.push((e as CustomEvent).detail.currentTime));
    audio.currentTime = 1;
    audio.emit("timeupdate");
    audio.currentTime = 2;
    audio.emit("timeupdate");
    audio.currentTime = 3;
    audio.emit("timeupdate");
    expect(updates).toHaveLength(0); // not flushed yet
    raf!(0);
    expect(updates).toEqual([3]); // single coalesced dispatch with latest time
  });

  it("setCues installs cues and emits cueschange then cuechange", () => {
    const { audio, controller } = setup({ duration: 100 });
    audio.currentTime = 1;
    const events: string[] = [];
    controller.addEventListener("cueschange", () => events.push("cueschange"));
    controller.addEventListener("cuechange", () => events.push("cuechange"));
    controller.setCues(cues);
    expect(events).toEqual(["cueschange", "cuechange"]);
    expect(controller.currentCueIndex).toBe(0);
    expect(controller.transcriptLoaded).toBe(true);
    expect(controller.transcriptLoading).toBe(false);
  });

  it("hasTranscript reflects url / cues / null", () => {
    expect(setup({ transcript: { url: "/x" } }).controller.hasTranscript).toBe(true);
    expect(setup({ transcript: { cues } }).controller.hasTranscript).toBe(true);
    expect(setup({ transcript: null }).controller.hasTranscript).toBe(false);
  });

  it("requestTranscript emits once + sets loading; setCues clears it; no refetch after loaded", () => {
    const { controller } = setup({ transcript: { url: "/x" } });
    const urls: string[] = [];
    controller.addEventListener("transcriptrequested", (e) => urls.push((e as CustomEvent).detail.url));
    expect(controller.transcriptLoaded).toBe(false);
    controller.requestTranscript();
    expect(urls).toEqual(["/x"]);
    expect(controller.transcriptLoading).toBe(true);
    controller.requestTranscript(); // no-op while loading
    expect(urls).toEqual(["/x"]);
    controller.setCues(cues);
    expect(controller.transcriptLoaded).toBe(true);
    expect(controller.transcriptLoading).toBe(false);
    controller.requestTranscript(); // no-op after loaded
    expect(urls).toEqual(["/x"]);
  });

  it("requestTranscript is a no-op when cues are inline (already loaded)", () => {
    const { controller } = setup({ transcript: { cues } });
    const urls: string[] = [];
    controller.addEventListener("transcriptrequested", () => urls.push("x"));
    expect(controller.transcriptLoaded).toBe(true);
    controller.requestTranscript();
    expect(urls).toEqual([]);
  });

  it("transcriptFailed clears loading without loaded, emits transcripterror, allows retry", () => {
    const { controller } = setup({ transcript: { url: "/x" } });
    const events: string[] = [];
    controller.addEventListener("transcriptrequested", () => events.push("req"));
    controller.addEventListener("transcripterror", () => events.push("err"));
    controller.requestTranscript();
    controller.transcriptFailed();
    expect(controller.transcriptLoading).toBe(false);
    expect(controller.transcriptLoaded).toBe(false);
    expect(events).toEqual(["req", "err"]);
    controller.transcriptFailed(); // no-op when not loading
    expect(events).toEqual(["req", "err"]);
    controller.requestTranscript(); // retry allowed
    expect(events).toEqual(["req", "err", "req"]);
  });

  it("removes listeners on destroy", () => {
    const { audio, controller } = setup({ duration: 100 });
    const updates: number[] = [];
    controller.addEventListener("timeupdate", () => updates.push(1));
    controller.destroy();
    audio.currentTime = 5;
    audio.emit("timeupdate");
    expect(updates).toHaveLength(0);
    expect(audio.pause).toHaveBeenCalled();
    controller.destroy(); // idempotent
  });
});
