// Framework-free audio controller: the single source of truth for playback
// state. Owns one HTMLAudioElement and a sorted cue/chapter model, and emits
// CustomEvents that the (UI-agnostic) views subscribe to. Extends the native
// EventTarget so the same pub/sub is reused unchanged by a future persistent
// player.

import { isFallbackTranscript, isInlineTranscript } from "./types";
import type { Chapter, Cue, PlayerPayload } from "./types";

// Small seek offset so seeking "to a cue" lands strictly inside it
// (start is inclusive, end exclusive).
const CUE_SEEK_EPSILON = 0.01;

function isFiniteNumber(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export class AudioController extends EventTarget {
  readonly audio: HTMLAudioElement;
  readonly payload: PlayerPayload;
  private cues: Cue[];
  private readonly chapters: Chapter[];
  private cueIndex = -1;
  private chapterIndex = -1;
  private frameScheduled = false;
  private destroyed = false;
  // Transcript loading state (revision 4): the transcript is fetched lazily on
  // first open, never inlined into the page. `transcriptUrl` is set when the
  // payload carries a `{url}`; `loaded` flips once real cues arrive via
  // setCues(); `loading` is true between requestTranscript() and setCues()/
  // transcriptFailed().
  private readonly transcriptUrl?: string;
  private loading = false;
  private loaded: boolean;
  private readonly boundListeners: Array<[string, EventListener]>;

  constructor(audio: HTMLAudioElement, payload: PlayerPayload) {
    super();
    this.audio = audio;
    this.payload = payload;
    // Inline `{cues}` is only ever supplied by the endpoint hydration or tests;
    // the rendered page supplies `{url}` (lazy) or `null` (no transcript).
    this.cues = isInlineTranscript(payload.transcript) ? payload.transcript.cues.slice() : [];
    this.chapters = payload.chapters.slice();
    this.transcriptUrl = isFallbackTranscript(payload.transcript) ? payload.transcript.url : undefined;
    // Cues supplied inline count as already loaded; a url-only transcript is
    // unloaded until requestTranscript() -> fetch -> setCues().
    this.loaded = isInlineTranscript(payload.transcript);

    this.boundListeners = [
      ["play", () => this.dispatch("play")],
      ["pause", () => this.dispatch("pause")],
      ["timeupdate", () => this.scheduleFrame()],
      ["durationchange", () => this.onDurationChange()],
      ["seeking", () => this.dispatch("seeking", { currentTime: this.currentTime })],
      ["seeked", () => this.onSeeked()],
      ["ended", () => this.onEnded()],
      ["error", () => this.onError()],
    ];
    for (const [name, listener] of this.boundListeners) {
      this.audio.addEventListener(name, listener);
    }

    // Establish initial indices from the (possibly 0) current time.
    this.refreshIndices(false);
  }

  // ---- getters --------------------------------------------------------------

  get currentTime(): number {
    return this.audio.currentTime || 0;
  }

  get duration(): number | null {
    if (isFiniteNumber(this.payload.duration)) {
      return this.payload.duration;
    }
    return isFiniteNumber(this.audio.duration) ? this.audio.duration : null;
  }

  get paused(): boolean {
    return this.audio.paused;
  }

  get currentChapterIndex(): number {
    return this.chapterIndex;
  }

  get currentCueIndex(): number {
    return this.cueIndex;
  }

  getCues(): readonly Cue[] {
    return this.cues;
  }

  getChapters(): readonly Chapter[] {
    return this.chapters;
  }

  // True when the audio has a transcript at all (inline cues or a lazy url).
  get hasTranscript(): boolean {
    return this.payload.transcript != null;
  }

  // True between requestTranscript() and the resolving setCues()/transcriptFailed().
  get transcriptLoading(): boolean {
    return this.loading;
  }

  // True once real cues have been installed (inline or via a successful fetch).
  get transcriptLoaded(): boolean {
    return this.loaded;
  }

  // ---- transport ------------------------------------------------------------

  async play(): Promise<void> {
    try {
      await this.audio.play();
    } catch (error) {
      // A play() interrupted by a pause()/load rejects with AbortError; that is
      // not a real failure and must be swallowed.
      if ((error as DOMException)?.name !== "AbortError") {
        this.dispatch("error", { error });
      }
    }
  }

  pause(): void {
    this.audio.pause();
  }

  toggle(): void {
    if (this.audio.paused) {
      void this.play();
    } else {
      this.pause();
    }
  }

  seek(seconds: number): void {
    const lower = Math.max(0, seconds);
    const duration = this.duration;
    const clamped = isFiniteNumber(duration) ? Math.min(lower, duration) : lower;
    this.audio.currentTime = clamped;
    // Update model + listeners immediately so dragging the bar moves the
    // transcript/chapters without waiting for a media event.
    this.dispatch("seeking", { currentTime: clamped });
    this.refreshIndices(true);
    this.emitTimeUpdate();
    this.dispatch("seeked", { currentTime: clamped });
  }

  seekToCue(index: number): void {
    const cue = this.cues[index];
    if (cue) {
      this.seek(cue.start + CUE_SEEK_EPSILON);
      // User-initiated navigation (a transcript-line click). Distinct from the
      // low-level seek() used by scrubbing and the initial ?t= deep-link, so
      // consumers can treat cue/chapter clicks as engagement without reacting
      // to programmatic seeks.
      this.dispatch("navseek", { currentTime: this.currentTime });
    }
  }

  seekToChapter(index: number): void {
    const chapter = this.chapters[index];
    if (chapter) {
      this.seek(chapter.start);
      this.dispatch("navseek", { currentTime: this.currentTime });
    }
  }

  // ---- lazy transcript loading ---------------------------------------------

  // Idempotent: ask the player (the sole fetcher) to load the transcript. Only
  // emits when there is a transcript url that is not already loaded or loading.
  // A no-op while loading or after a successful load.
  requestTranscript(): void {
    if (this.loaded || this.loading || !this.transcriptUrl) {
      return;
    }
    this.loading = true;
    this.dispatch("transcriptrequested", { url: this.transcriptUrl });
  }

  // Called by the player when the fetch fails: clear loading WITHOUT marking
  // loaded, so a later requestTranscript() may retry. No cues are installed.
  transcriptFailed(): void {
    if (!this.loading) {
      return;
    }
    this.loading = false;
    this.dispatch("transcripterror", {});
  }

  // Install real cues (inline endpoint hydration or a successful fetch). Marks
  // the transcript loaded, clears loading, and recomputes the current cue.
  setCues(cues: Cue[]): void {
    this.cues = cues.slice();
    this.loaded = true;
    this.loading = false;
    const previous = this.cueIndex;
    this.cueIndex = this.computeCueIndex(this.currentTime);
    this.dispatch("cueschange", { count: this.cues.length });
    if (this.cueIndex !== previous) {
      this.dispatch("cuechange", { index: this.cueIndex });
    }
  }

  // ---- lifecycle ------------------------------------------------------------

  destroy(): void {
    if (this.destroyed) {
      return;
    }
    this.destroyed = true;
    for (const [name, listener] of this.boundListeners) {
      this.audio.removeEventListener(name, listener);
    }
    try {
      this.audio.pause();
    } catch {
      // ignore — element may already be detached
    }
    this.cues = [];
    this.cueIndex = -1;
    this.chapterIndex = -1;
  }

  // ---- internals ------------------------------------------------------------

  private scheduleFrame(): void {
    if (this.frameScheduled || this.destroyed) {
      return;
    }
    this.frameScheduled = true;
    const raf =
      typeof requestAnimationFrame === "function"
        ? requestAnimationFrame
        : (cb: FrameRequestCallback) => setTimeout(() => cb(0), 16) as unknown as number;
    raf(() => {
      this.frameScheduled = false;
      if (this.destroyed) {
        return;
      }
      this.emitTimeUpdate();
      this.refreshIndices(true);
    });
  }

  private emitTimeUpdate(): void {
    this.dispatch("timeupdate", { currentTime: this.currentTime, duration: this.duration });
  }

  private onDurationChange(): void {
    this.dispatch("durationchange", { duration: this.duration });
    this.refreshIndices(true);
  }

  private onSeeked(): void {
    this.refreshIndices(true);
    this.dispatch("seeked", { currentTime: this.currentTime });
  }

  private onEnded(): void {
    // Explicit exception to the exclusive-end rule: keep the last cue/chapter
    // highlighted at the very end instead of blanking out.
    const newCue = this.cues.length ? this.cues.length - 1 : -1;
    const newChapter = this.chapters.length ? this.chapters.length - 1 : -1;
    this.applyIndices(newCue, newChapter, true);
    this.dispatch("pause");
  }

  private onError(): void {
    this.dispatch("error", { error: this.audio.error });
  }

  private refreshIndices(emit: boolean): void {
    const t = this.currentTime;
    this.applyIndices(this.computeCueIndex(t), this.computeChapterIndex(t), emit);
  }

  private applyIndices(newCue: number, newChapter: number, emit: boolean): void {
    if (newCue !== this.cueIndex) {
      this.cueIndex = newCue;
      if (emit) {
        this.dispatch("cuechange", { index: this.cueIndex });
      }
    }
    if (newChapter !== this.chapterIndex) {
      this.chapterIndex = newChapter;
      if (emit) {
        this.dispatch("chapterchange", { index: this.chapterIndex });
      }
    }
  }

  private computeCueIndex(t: number): number {
    if (this.cues.length === 0) {
      return -1;
    }
    const duration = this.duration;
    if (isFiniteNumber(duration) && t >= duration) {
      return this.cues.length - 1; // ended exception
    }
    let result = -1;
    for (let i = 0; i < this.cues.length; i++) {
      const cue = this.cues[i];
      if (cue.start <= t && t < cue.end) {
        result = i; // overlap: last matching cue wins
      }
    }
    return result;
  }

  private computeChapterIndex(t: number): number {
    if (this.chapters.length === 0) {
      return -1;
    }
    const duration = this.duration;
    if (isFiniteNumber(duration) && t >= duration) {
      return this.chapters.length - 1; // ended exception
    }
    if (t < this.chapters[0].start) {
      return -1;
    }
    let result = -1;
    for (let i = 0; i < this.chapters.length; i++) {
      if (this.chapters[i].start <= t) {
        result = i;
      } else {
        break;
      }
    }
    return result;
  }

  private dispatch(type: string, detail: Record<string, unknown> = {}): void {
    this.dispatchEvent(new CustomEvent(type, { detail }));
  }
}
