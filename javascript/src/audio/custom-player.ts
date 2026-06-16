// Entry point for the custom audio player bundle. Imports the plain CSS (Vite
// bundles it into the cast Vite output) and registers all custom elements.
// Zero runtime dependencies.

import "./custom-player.css";

import { defineCastAudioPlayer } from "./audio-player-element";
import { defineCastChapters } from "./chapters-element";
import { defineCastTranscript } from "./transcript-element";

export function defineCustomPlayer(): void {
  defineCastAudioPlayer();
  defineCastChapters();
  defineCastTranscript();
}

defineCustomPlayer();
