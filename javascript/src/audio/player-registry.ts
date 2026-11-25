// Module-level registry mapping player id -> AudioController, plus the
// `cast:player-ready` lifecycle event used so views can resolve a controller
// that connects after them (e.g. transcript placed above the player in the DOM,
// or htmx swaps).

import { AudioController } from "./audio-controller";

export const PLAYER_READY_EVENT = "cast:player-ready";

const registry = new Map<string, AudioController>();

export function registerController(id: string, controller: AudioController): void {
  const existing = registry.get(id);
  if (existing && existing !== controller) {
    // Duplicate id: last wins, but the previous controller must be torn down so
    // it does not leak listeners across an htmx swap.
    console.warn(`cast-audio-player: duplicate id "${id}" — replacing previous controller`);
    existing.destroy();
  }
  registry.set(id, controller);
  document.dispatchEvent(new CustomEvent(PLAYER_READY_EVENT, { detail: { playerId: id } }));
}

export function unregisterController(id: string, controller: AudioController): void {
  if (registry.get(id) === controller) {
    registry.delete(id);
  }
}

export function getController(id: string): AudioController | undefined {
  return registry.get(id);
}

// Observe the controller for this ID, including replacements, until canceled.
export function watchController(id: string, callback: (controller: AudioController) => void): () => void {
  const notify = () => {
    const controller = getController(id);
    if (controller) {
      callback(controller);
    }
  };
  const listener = (event: Event) => {
    const detail = (event as CustomEvent<{ playerId: string }>).detail;
    if (detail?.playerId === id) {
      notify();
    }
  };
  document.addEventListener(PLAYER_READY_EVENT, listener);
  notify();
  return () => document.removeEventListener(PLAYER_READY_EVENT, listener);
}

// Test-only helper to reset module state between cases.
export function _clearRegistry(): void {
  registry.clear();
}
