// Base class for the coupled views (<cast-transcript>, <cast-chapters>). Handles
// resolving the controller by the `for` attribute (now or via the late
// `cast:player-ready` retry) and precise listener cleanup on disconnect so no
// controller leaks across htmx swaps.

import { AudioController } from "./audio-controller";
import { whenController } from "./player-registry";

export abstract class CastPlayerView extends HTMLElement {
  protected controller?: AudioController;
  private cancelPending?: () => void;
  private listeners: Array<[string, EventListener]> = [];

  connectedCallback(): void {
    const forId = this.getAttribute("for");
    if (!forId) {
      return;
    }
    this.renderInitial();
    this.cancelPending = whenController(forId, (controller) => {
      this.cancelPending = undefined;
      this.controller = controller;
      this.onController(controller);
    });
  }

  disconnectedCallback(): void {
    if (this.cancelPending) {
      this.cancelPending();
      this.cancelPending = undefined;
    }
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

  // Called once the controller is resolved.
  protected abstract onController(controller: AudioController): void;
}
