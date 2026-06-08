// <cast-transcript for="..."> — a collapsible, django-chat-style transcript:
// a timestamp column + speaker-labelled text, current-cue highlight with
// follow-along auto-scroll, click-to-seek, and search (visible match marks +
// scroll-to-match). Never fetches; it only reads controller cues (the player
// owns all fetching). Renders cue text via textContent only (XSS-safe).

import { AudioController } from "./audio-controller";
import { formatTime } from "./format";
import type { Cue } from "./types";
import { CastPlayerView } from "./view-base";

const FOLLOW_STORAGE_KEY = "cast-transcript-follow";
const TABBABLE_STORAGE_KEY = "cast-transcript-tabbable";

function readBool(key: string, fallback: boolean): boolean {
  try {
    const value = window.localStorage.getItem(key);
    return value === null ? fallback : value === "true";
  } catch {
    return fallback;
  }
}

function writeBool(key: string, value: boolean): void {
  try {
    window.localStorage.setItem(key, value ? "true" : "false");
  } catch {
    /* storage unavailable */
  }
}

const CHEVRON =
  '<svg class="cast-panel__chevron" width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5l8 7-8 7z"/></svg>';

// Keyboard glyph for the demoted "keyboard-navigable cues" preference: an
// icon-only secondary control instead of a primary "Tab cues" toolbar button.
const KEYBOARD_ICON =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/></svg>';

export class CastTranscriptElement extends CastPlayerView {
  private section?: HTMLElement;
  private panelBody?: HTMLElement;
  private scroll?: HTMLElement;
  private list?: HTMLElement;
  private toggleButton?: HTMLButtonElement;
  private countLabel?: HTMLElement;
  private searchInput?: HTMLInputElement;
  private searchStatus?: HTMLElement;
  private followButton?: HTMLButtonElement;
  private tabbableButton?: HTMLButtonElement;
  private loadingEl?: HTMLElement;
  private cueButtons: HTMLButtonElement[] = [];
  private cues: readonly Cue[] = [];
  private activeIndex = -1;
  private open = false;
  private follow = true;
  private tabbable = false;
  private matchIndices: number[] = [];
  private matchCursor = -1;

  protected onController(controller: AudioController): void {
    if (!controller.hasTranscript) {
      return; // no transcript at all -> render nothing
    }
    if (controller.transcriptLoaded && controller.getCues().length === 0) {
      return; // loaded but empty (no cues, no pending url) -> render nothing
    }
    // Always start collapsed — the reader clicks to open (no persisted open
    // state), so an episode never loads with the transcript already expanded
    // and no transcript fetch happens until an explicit open.
    this.open = false;
    this.follow = readBool(FOLLOW_STORAGE_KEY, true);
    this.tabbable = readBool(TABBABLE_STORAGE_KEY, false);
    this.build();
    if (controller.transcriptLoaded) {
      this.renderCues(controller.getCues());
    }
    this.listen("cueschange", () => this.renderCues(controller.getCues()));
    this.listen("cuechange", () => this.setActive(controller.currentCueIndex));
    this.listen("transcripterror", () => this.onTranscriptError());
    // Accordion: when the sibling panel (chapters) opens, collapse this one so
    // only one panel is open at a time.
    this.listen("castpanelopen", (event) => {
      const detail = (event as CustomEvent<{ kind: string }>).detail;
      if (detail && detail.kind !== "transcript" && this.open) {
        this.toggleOpen();
      }
    });
  }

  // ---- structure ------------------------------------------------------------

  private build(): void {
    const section = document.createElement("section");
    section.className = "cast-transcript cast-panel";
    section.setAttribute("aria-label", "Transcript");
    if (this.open) {
      section.classList.add("is-open");
    }

    const header = document.createElement("div");
    header.className = "cast-panel__header";

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "cast-panel__toggle";
    toggle.setAttribute("aria-expanded", this.open ? "true" : "false");
    toggle.innerHTML = CHEVRON;
    const label = document.createElement("span");
    label.textContent = "Transcript";
    // The line count lives inside the open panel (the tools row), not on the
    // toggle — so the collapsed pill keeps a constant width.
    toggle.append(label);
    toggle.addEventListener("click", () => this.toggleOpen());
    this.toggleButton = toggle;

    header.append(toggle);

    // The body is the flex item; a `reveal` wrapper carries the card chrome and
    // the spring reveal/collapse motion, and an inner `clip` is the
    // overflow-hidden track that the grid-rows animation expands (see the
    // `.cast-panel__reveal` rules in custom-player.css). Restructuring like this
    // keeps the collapsed panel out of the flex flow (body is display:none) so
    // it adds no row gap, while still animating open/closed height + opacity.
    const body = document.createElement("div");
    body.className = "cast-panel__body";
    const reveal = document.createElement("div");
    reveal.className = "cast-panel__reveal";
    const clip = document.createElement("div");
    clip.className = "cast-panel__clip";
    const scroll = document.createElement("div");
    scroll.className = "cast-panel__scroll";
    const list = document.createElement("div");
    list.className = "cast-transcript__cues";
    scroll.appendChild(list);
    // Tools (search / follow / tab-cues) live at the top of the body, not in the
    // button row, so the collapsed toggle stays a compact pill.
    clip.append(this.buildTools(), scroll);
    reveal.appendChild(clip);
    body.appendChild(reveal);
    this.panelBody = body;
    this.scroll = scroll;
    this.list = list;
    // A collapsed panel is only visually clipped; mark it inert so its buttons
    // are removed from the tab order and not interactive while hidden.
    this.applyInert();

    section.append(header, body);
    this.section = section;
    this.appendChild(section);
  }

  private buildTools(): HTMLElement {
    const tools = document.createElement("div");
    tools.className = "cast-panel__tools";

    const count = document.createElement("span");
    count.className = "cast-panel__count";
    this.countLabel = count;

    const search = document.createElement("input");
    search.type = "search";
    search.className = "cast-transcript__search-input";
    search.setAttribute("aria-label", "Search transcript");
    search.placeholder = "Search…";
    search.addEventListener("input", () => this.runSearch(search.value));
    this.searchInput = search;

    const prev = document.createElement("button");
    prev.type = "button";
    prev.className = "cast-transcript__nav";
    prev.textContent = "‹";
    prev.setAttribute("aria-label", "Previous match");
    prev.addEventListener("click", () => this.gotoMatch(-1));

    const next = document.createElement("button");
    next.type = "button";
    next.className = "cast-transcript__nav";
    next.textContent = "›";
    next.setAttribute("aria-label", "Next match");
    next.addEventListener("click", () => this.gotoMatch(1));

    const status = document.createElement("span");
    status.className = "cast-transcript__search-status";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    this.searchStatus = status;

    const follow = document.createElement("button");
    follow.type = "button";
    follow.className = "cast-transcript__follow";
    follow.textContent = "Follow";
    follow.setAttribute("aria-pressed", this.follow ? "true" : "false");
    follow.addEventListener("click", () => this.toggleFollow());
    this.followButton = follow;

    // Keyboard-navigable-cues preference, demoted to an icon-only secondary
    // control: the old "Tab cues" text read as a primary action and did not
    // explain itself. The accessible name + tooltip carry the meaning; the
    // persisted `cast-transcript-tabbable` preference is unchanged.
    const tab = document.createElement("button");
    tab.type = "button";
    tab.className = "cast-transcript__iconpref cast-transcript__tabpref";
    tab.innerHTML = KEYBOARD_ICON;
    tab.title = "Make transcript lines keyboard-focusable with Tab";
    tab.setAttribute("aria-label", "Keyboard-navigable cues");
    tab.setAttribute("aria-pressed", this.tabbable ? "true" : "false");
    tab.addEventListener("click", () => {
      this.tabbable = !this.tabbable;
      tab.setAttribute("aria-pressed", this.tabbable ? "true" : "false");
      writeBool(TABBABLE_STORAGE_KEY, this.tabbable);
      this.applyTabbable();
    });
    this.tabbableButton = tab;

    tools.append(count, search, prev, next, status, follow, tab);
    return tools;
  }

  private showLoading(): void {
    if (!this.list || this.loadingEl) {
      return;
    }
    this.list.textContent = ""; // clear any prior "unavailable" message before retrying
    // Busy semantics on the scroll region so assistive tech announces the
    // in-flight fetch; cleared when cues (or an error) land. Reserving the row
    // height keeps the toolbar/panel from shifting when cues replace it.
    this.scroll?.setAttribute("aria-busy", "true");
    const loading = document.createElement("p");
    loading.className = "cast-transcript__loading";
    loading.setAttribute("role", "status");
    const spinner = document.createElement("span");
    spinner.className = "cast-transcript__spinner";
    spinner.setAttribute("aria-hidden", "true");
    loading.append(spinner, document.createTextNode("Loading transcript…"));
    this.list.appendChild(loading);
    this.loadingEl = loading;
  }

  private onTranscriptError(): void {
    if (!this.list) {
      return;
    }
    this.list.textContent = "";
    this.loadingEl = undefined;
    this.scroll?.removeAttribute("aria-busy");
    const message = document.createElement("p");
    message.className = "cast-transcript__loading";
    message.textContent = "Transcript unavailable.";
    this.list.appendChild(message);
  }

  // ---- open / follow toggles ------------------------------------------------

  private toggleOpen(): void {
    this.open = !this.open;
    this.section?.classList.toggle("is-open", this.open);
    this.toggleButton?.setAttribute("aria-expanded", this.open ? "true" : "false");
    this.applyInert();
    if (this.open && this.controller) {
      // Accordion: tell the sibling chapters panel to collapse.
      this.controller.dispatchEvent(new CustomEvent("castpanelopen", { detail: { kind: "transcript" } }));
      // Lazy load on first open: fetch the transcript only now, never on connect.
      if (!this.controller.transcriptLoaded && !this.controller.transcriptLoading) {
        this.showLoading();
        this.controller.requestTranscript();
      }
      this.setActive(this.controller.currentCueIndex, true);
    }
  }

  private applyInert(): void {
    if (!this.panelBody) {
      return;
    }
    if (this.open) {
      this.panelBody.removeAttribute("inert");
    } else {
      this.panelBody.setAttribute("inert", "");
    }
  }

  private toggleFollow(): void {
    this.follow = !this.follow;
    this.followButton?.setAttribute("aria-pressed", this.follow ? "true" : "false");
    writeBool(FOLLOW_STORAGE_KEY, this.follow);
    if (this.follow && this.controller) {
      this.setActive(this.controller.currentCueIndex, true);
    }
  }

  // ---- cue rendering --------------------------------------------------------

  private renderCues(cues: readonly Cue[]): void {
    if (!this.list) {
      return;
    }
    this.cues = cues;
    this.list.textContent = "";
    this.loadingEl = undefined;
    this.scroll?.removeAttribute("aria-busy");
    this.cueButtons = [];
    if (this.countLabel) {
      this.countLabel.textContent = cues.length ? `${cues.length} lines` : "";
    }

    // Labelled (diarized) transcripts read like dialogue: a speaker heading per
    // turn, and a muted time anchor only at the start of each speaker run — not a
    // timestamp on every line. Plain transcripts keep a timestamp per cue. The
    // continuation timestamps still exist (visually hidden via CSS) so the grid
    // stays aligned and click-to-seek keeps working per cue.
    const labelled = cues.some((cue) => cue.speaker.trim() !== "");
    this.list.classList.toggle("cast-transcript__cues--labelled", labelled);

    let previousSpeaker = "";
    cues.forEach((cue, index) => {
      // A speaker change (including a reset to an empty speaker) starts a new
      // run: a heading for a named speaker, and a time anchor on the first line.
      // The very first cue always anchors, so a leading empty-speaker cue (e.g.
      // intro music before anyone speaks) keeps its timestamp instead of being
      // treated as a continuation of a non-existent prior run.
      const runStart = index === 0 || cue.speaker !== previousSpeaker;
      if (cue.speaker && runStart) {
        const speaker = document.createElement("div");
        speaker.className = "cast-transcript__speaker";
        speaker.textContent = cue.speaker; // textContent only
        this.list!.appendChild(speaker);
      }
      previousSpeaker = cue.speaker;

      const button = document.createElement("button");
      button.type = "button";
      button.className = "cast-transcript__cue";
      if (runStart) {
        button.classList.add("is-run-start");
      }
      button.tabIndex = this.tabbable ? 0 : -1;
      button.dataset.start = String(cue.start);
      button.dataset.end = String(cue.end);

      const time = document.createElement("span");
      time.className = "cast-transcript__time";
      time.textContent = formatTime(cue.start);

      const text = document.createElement("span");
      text.className = "cast-transcript__text";
      text.textContent = cue.text; // textContent only — never innerHTML

      button.append(time, text);
      button.addEventListener("click", () => this.controller?.seekToCue(index));
      this.list!.appendChild(button);
      this.cueButtons.push(button);
    });

    this.activeIndex = -1;
    if (this.controller) {
      this.setActive(this.controller.currentCueIndex);
    }
    if (this.searchInput && this.searchInput.value) {
      this.runSearch(this.searchInput.value);
    }
  }

  // ---- highlight + follow-along scroll --------------------------------------

  private setActive(index: number, forceScroll = false): void {
    if (index !== this.activeIndex) {
      const previous = this.cueButtons[this.activeIndex];
      if (previous) {
        previous.removeAttribute("aria-current");
        previous.classList.remove("is-current");
      }
      this.activeIndex = index;
      const current = this.cueButtons[index];
      if (current) {
        current.setAttribute("aria-current", "true");
        current.classList.add("is-current");
      }
    }
    const current = this.cueButtons[index];
    if (current && this.open && (this.follow || forceScroll)) {
      this.scrollIntoView(current);
    }
  }

  private scrollIntoView(element: HTMLElement): void {
    const reduce =
      typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    try {
      element.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "nearest" });
    } catch {
      /* unsupported in some environments */
    }
  }

  // ---- search ---------------------------------------------------------------

  private runSearch(query: string): void {
    const needle = query.trim().toLowerCase();
    this.matchIndices = [];
    this.matchCursor = -1;
    this.cues.forEach((cue, index) => {
      const textSpan = this.cueButtons[index]?.querySelector<HTMLElement>(".cast-transcript__text");
      if (!textSpan) {
        return;
      }
      textSpan.textContent = cue.text; // clear previous marks (textContent only)
      if (needle && cue.text.toLowerCase().includes(needle)) {
        this.markMatches(textSpan, cue.text, needle);
        this.matchIndices.push(index);
      }
    });
    this.announceMatches(needle);
    if (needle && this.matchIndices.length) {
      // Scroll to the first match so it's visible, but keep focus in the search
      // input so the user can keep typing.
      this.gotoMatch(1, false);
    }
  }

  private markMatches(textSpan: HTMLElement, text: string, needle: string): void {
    const haystack = text.toLowerCase();
    textSpan.textContent = "";
    let cursor = 0;
    let found = haystack.indexOf(needle, cursor);
    while (found !== -1) {
      if (found > cursor) {
        textSpan.appendChild(document.createTextNode(text.slice(cursor, found)));
      }
      const mark = document.createElement("mark");
      mark.textContent = text.slice(found, found + needle.length);
      textSpan.appendChild(mark);
      cursor = found + needle.length;
      found = haystack.indexOf(needle, cursor);
    }
    if (cursor < text.length) {
      textSpan.appendChild(document.createTextNode(text.slice(cursor)));
    }
  }

  private announceMatches(needle: string): void {
    if (!this.searchStatus) {
      return;
    }
    if (!needle) {
      this.searchStatus.textContent = "";
      return;
    }
    const count = this.matchIndices.length;
    this.searchStatus.textContent = count === 1 ? "1 match" : `${count} matches`;
  }

  private gotoMatch(direction: 1 | -1, focus = true): void {
    if (this.matchIndices.length === 0) {
      return;
    }
    // Clear the previously active match highlight.
    this.list?.querySelectorAll("mark.is-active-match").forEach((m) => m.classList.remove("is-active-match"));
    if (this.matchCursor === -1) {
      this.matchCursor = direction === 1 ? 0 : this.matchIndices.length - 1;
    } else {
      this.matchCursor = (this.matchCursor + direction + this.matchIndices.length) % this.matchIndices.length;
    }
    const cueIndex = this.matchIndices[this.matchCursor];
    const button = this.cueButtons[cueIndex];
    if (button) {
      button.querySelector("mark")?.classList.add("is-active-match");
      this.scrollIntoView(button);
      if (focus) {
        button.focus(); // explicit prev/next: scroll + focus, never seek
      }
    }
  }

  // ---- keyboard-navigable preference ---------------------------------------

  private applyTabbable(): void {
    for (const button of this.cueButtons) {
      button.tabIndex = this.tabbable ? 0 : -1;
    }
  }
}

export const CAST_TRANSCRIPT_TAG = "cast-transcript";

export function defineCastTranscript(): void {
  if (!customElements.get(CAST_TRANSCRIPT_TAG)) {
    customElements.define(CAST_TRANSCRIPT_TAG, CastTranscriptElement);
  }
}
