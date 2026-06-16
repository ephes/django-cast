// Shared types for the custom audio player. These mirror the backend
// `PlayerPayload` produced by `src/cast/player.py::build_player_payload`.

export type Cue = { start: number; end: number; speaker: string; text: string };
export type Chapter = { start: number; title: string };

export type InlineTranscript = { cues: Cue[] };
export type FallbackTranscript = { url: string };
// `null` means the audio has no transcript at all. On the rendered page the
// transcript is never inlined: it is either a `{url}` fetched lazily on first
// open, or `null`. `{cues}` is only ever produced by the transcript endpoint
// (handed to the controller via setCues) or constructed directly in tests.
export type TranscriptPayload = InlineTranscript | FallbackTranscript | null;

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

export function isInlineTranscript(t: TranscriptPayload): t is InlineTranscript {
  return !!t && Array.isArray((t as InlineTranscript).cues);
}

export function isFallbackTranscript(t: TranscriptPayload): t is FallbackTranscript {
  return !!t && typeof (t as FallbackTranscript).url === "string";
}
