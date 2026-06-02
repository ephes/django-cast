// Shared types for the custom audio player. These mirror the backend
// `PlayerPayload` produced by `src/cast/player.py::build_player_payload`.

export type Cue = { start: number; end: number; speaker: string; text: string };
export type Chapter = { start: number; title: string };

export type InlineTranscript = { cues: Cue[] };
export type FallbackTranscript = { url: string };
export type TranscriptPayload = InlineTranscript | FallbackTranscript;

export type Source = { type: string; src: string };

export type PlayerPayload = {
  audioId: number;
  title: string;
  subtitle: string;
  duration: number | null; // seconds; null until media metadata loads
  poster: string; // "" if none
  sources: Source[];
  chapters: Chapter[];
  transcript: TranscriptPayload;
};

export function isFallbackTranscript(t: TranscriptPayload): t is FallbackTranscript {
  return typeof (t as FallbackTranscript).url === "string";
}
