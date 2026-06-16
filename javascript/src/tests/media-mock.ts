// jsdom does not implement HTMLMediaElement playback. This patches the
// prototype with controllable backing fields so real <audio> elements created
// by the components behave deterministically in tests.

import { vi } from "vitest";

interface MockMedia {
  __paused?: boolean;
  __currentTime?: number;
  __duration?: number;
  __error?: MediaError | null;
}

export function installMediaMock(): void {
  const proto = window.HTMLMediaElement.prototype as unknown as Record<string, unknown>;
  Object.defineProperty(proto, "paused", {
    configurable: true,
    get(this: MockMedia) {
      return this.__paused ?? true;
    },
  });
  Object.defineProperty(proto, "currentTime", {
    configurable: true,
    get(this: MockMedia) {
      return this.__currentTime ?? 0;
    },
    set(this: MockMedia, value: number) {
      this.__currentTime = value;
    },
  });
  Object.defineProperty(proto, "duration", {
    configurable: true,
    get(this: MockMedia) {
      return this.__duration ?? NaN;
    },
    set(this: MockMedia, value: number) {
      this.__duration = value;
    },
  });
  Object.defineProperty(proto, "error", {
    configurable: true,
    get(this: MockMedia) {
      return this.__error ?? null;
    },
    set(this: MockMedia, value: MediaError | null) {
      this.__error = value;
    },
  });
  proto.play = vi.fn(function (this: MockMedia & EventTarget) {
    this.__paused = false;
    this.dispatchEvent(new Event("play"));
    return Promise.resolve();
  });
  proto.pause = vi.fn(function (this: MockMedia & EventTarget) {
    this.__paused = true;
    this.dispatchEvent(new Event("pause"));
  });
}

// Run the controller's coalesced timeupdate synchronously.
export function installSyncRaf(): void {
  globalThis.requestAnimationFrame = ((cb: FrameRequestCallback) => {
    cb(0);
    return 0;
  }) as typeof requestAnimationFrame;
}
