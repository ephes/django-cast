// Base class for the coupled views (<cast-transcript>, <cast-chapters>). Handles
// binding by the `for` attribute and retiring controller listeners on replacement
// or disconnect.

import { AudioController } from "./audio-controller";
import { watchController } from "./player-registry";

export abstract class CastPlayerView extends HTMLElement {
  protected controller?: AudioController;
  private stopWatching?: () => void;
  private listeners: Array<[string, EventListener]> = [];

  connectedCallback(): void {
    const forId = this.getAttribute("for");
    if (!forId) {
      return;
    }
    this.renderInitial();
    this.stopWatching = watchController(forId, (controller) => {
      if (this.controller === controller) {
        return;
      }
      this.unbindController();
      this.controller = controller;
      this.onController(controller);
    });
  }

  disconnectedCallback(): void {
    this.stopWatching?.();
    this.stopWatching = undefined;
    this.unbindController();
  }

  private unbindController(): void {
    for (const [type, listener] of this.listeners) {
      this.controller?.removeEventListener(type, listener);
    }
    this.listeners = [];
    this.controller = undefined;
  }

  // Subscribe to a controller event and track it for cleanup. The listener may
  // accept the event (e.g. for accordion coordination); existing callers that
  // ignore it stay compatible.
  protected listen(type: string, listener: (event: Event) => void): void {
    this.controller?.addEventListener(type, listener as EventListener);
    this.listeners.push([type, listener as EventListener]);
  }

  // Optional pre-controller render (e.g. a transcript loading state).
  protected renderInitial(): void {}

  // Called when the initial or replacement controller is resolved.
  protected abstract onController(controller: AudioController): void;
}
