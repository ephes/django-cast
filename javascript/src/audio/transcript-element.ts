// <cast-transcript for="..."> — renders cues from controller state with
// speaker labels, current-cue highlight, auto-scroll, click-to-seek, search
// (mark-don't-hide), and an opt-in keyboard-navigable mode. Never fetches; it
// only reads controller cues (the player owns all fetching).

import { AudioController } from "./audio-controller";
import type { Cue } from "./types";
import { CastPlayerView } from "./view-base";

const TABBABLE_STORAGE_KEY = "cast-transcript-tabbable";

export class CastTranscriptElement extends CastPlayerView {
  private region?: HTMLElement;
  private list?: HTMLElement;
  private loadingEl?: HTMLElement;
  private searchInput?: HTMLInputElement;
  private searchStatus?: HTMLElement;
  private cueButtons: HTMLButtonElement[] = [];
  private cues: readonly Cue[] = [];
  private activeIndex = -1;
  private autoScroll = true;
  private tabbable = false;
  private matchIndices: number[] = [];
  private matchCursor = -1;

  protected onController(controller: AudioController): void {
    const cues = controller.getCues();
    if (cues.length === 0 && !controller.transcriptPending) {
      return; // render nothing
    }
    this.tabbable = this.readTabbablePreference();
    this.buildRegion();
    if (cues.length === 0 && controller.transcriptPending) {
      this.showLoading();
    } else {
      this.renderCues(cues);
    }
    this.listen("cueschange", () => this.renderCues(controller.getCues()));
    this.listen("cuechange", () => this.setActive(controller.currentCueIndex));
  }

  // ---- structure ------------------------------------------------------------

  private buildRegion(): void {
    const region = document.createElement("section");
    region.className = "cast-transcript";
    region.setAttribute("aria-label", "Transcript");

    const heading = document.createElement("h2");
    heading.className = "cast-transcript__heading";
    heading.textContent = "Transcript";

    region.appendChild(heading);
    region.appendChild(this.buildControls());

    const list = document.createElement("div");
    list.className = "cast-transcript__cues";
    this.list = list;
    region.appendChild(list);

    this.region = region;
    this.appendChild(region);
  }

  private buildControls(): HTMLElement {
    const controls = document.createElement("div");
    controls.className = "cast-transcript__controls";

    // Search
    const searchLabel = document.createElement("label");
    searchLabel.className = "cast-transcript__search";
    const searchText = document.createElement("span");
    searchText.textContent = "Search transcript";
    const search = document.createElement("input");
    search.type = "search";
    search.className = "cast-transcript__search-input";
    search.addEventListener("input", () => this.runSearch(search.value));
    searchLabel.append(searchText, search);
    this.searchInput = search;

    const prev = document.createElement("button");
    prev.type = "button";
    prev.className = "cast-transcript__match-prev";
    prev.textContent = "Previous match";
    prev.addEventListener("click", () => this.gotoMatch(-1));

    const next = document.createElement("button");
    next.type = "button";
    next.className = "cast-transcript__match-next";
    next.textContent = "Next match";
    next.addEventListener("click", () => this.gotoMatch(1));

    const status = document.createElement("div");
    status.className = "cast-transcript__search-status";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    this.searchStatus = status;

    // Auto-scroll toggle
    const autoScrollLabel = document.createElement("label");
    autoScrollLabel.className = "cast-transcript__toggle";
    const autoScrollInput = document.createElement("input");
    autoScrollInput.type = "checkbox";
    autoScrollInput.checked = this.autoScroll;
    autoScrollInput.addEventListener("change", () => {
      this.autoScroll = autoScrollInput.checked;
    });
    const autoScrollText = document.createElement("span");
    autoScrollText.textContent = "Auto-scroll";
    autoScrollLabel.append(autoScrollInput, autoScrollText);

    // Keyboard-navigable toggle (persisted)
    const tabbableLabel = document.createElement("label");
    tabbableLabel.className = "cast-transcript__toggle";
    const tabbableInput = document.createElement("input");
    tabbableInput.type = "checkbox";
    tabbableInput.checked = this.tabbable;
    tabbableInput.addEventListener("change", () => {
      this.tabbable = tabbableInput.checked;
      this.writeTabbablePreference(this.tabbable);
      this.applyTabbable();
    });
    const tabbableText = document.createElement("span");
    tabbableText.textContent = "Keyboard-navigable transcript";
    tabbableLabel.append(tabbableInput, tabbableText);

    controls.append(searchLabel, prev, next, status, autoScrollLabel, tabbableLabel);
    return controls;
  }

  private showLoading(): void {
    if (!this.list) {
      return;
    }
    const loading = document.createElement("p");
    loading.className = "cast-transcript__loading";
    loading.textContent = "Loading transcript…";
    this.list.appendChild(loading);
    this.loadingEl = loading;
  }

  // ---- cue rendering --------------------------------------------------------

  private renderCues(cues: readonly Cue[]): void {
    if (!this.list) {
      return;
    }
    this.cues = cues;
    this.list.textContent = "";
    this.loadingEl = undefined;
    this.cueButtons = [];

    cues.forEach((cue, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "cast-transcript__cue";
      button.tabIndex = this.tabbable ? 0 : -1;
      button.dataset.start = String(cue.start);
      button.dataset.end = String(cue.end);

      if (cue.speaker) {
        const speaker = document.createElement("span");
        speaker.className = "cast-transcript__speaker";
        speaker.textContent = cue.speaker;
        button.appendChild(speaker);
      }

      const text = document.createElement("span");
      text.className = "cast-transcript__text";
      text.textContent = cue.text; // textContent only — never innerHTML
      button.appendChild(text);

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

  // ---- highlight + auto-scroll ----------------------------------------------

  private setActive(index: number): void {
    if (index === this.activeIndex) {
      return;
    }
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
      if (this.autoScroll) {
        this.scrollTo(current);
      }
    }
  }

  private scrollTo(element: HTMLElement): void {
    const reduceMotion =
      typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    try {
      element.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "nearest" });
    } catch {
      // scrollIntoView may be unimplemented in some environments — ignore.
    }
  }

  // ---- search ---------------------------------------------------------------

  private runSearch(query: string): void {
    const needle = query.trim().toLowerCase();
    this.matchIndices = [];
    this.matchCursor = -1;
    this.cues.forEach((cue, index) => {
      const button = this.cueButtons[index];
      const textSpan = button?.querySelector<HTMLElement>(".cast-transcript__text");
      if (!textSpan) {
        return;
      }
      this.clearMarks(textSpan, cue.text);
      if (needle && cue.text.toLowerCase().includes(needle)) {
        this.markMatches(textSpan, cue.text, needle);
        this.matchIndices.push(index);
      }
    });
    this.announceMatches(needle);
  }

  private clearMarks(textSpan: HTMLElement, text: string): void {
    textSpan.textContent = text;
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

  private gotoMatch(direction: 1 | -1): void {
    if (this.matchIndices.length === 0) {
      return;
    }
    if (this.matchCursor === -1) {
      this.matchCursor = direction === 1 ? 0 : this.matchIndices.length - 1;
    } else {
      this.matchCursor =
        (this.matchCursor + direction + this.matchIndices.length) % this.matchIndices.length; // wrap
    }
    const cueIndex = this.matchIndices[this.matchCursor];
    const button = this.cueButtons[cueIndex];
    if (button) {
      this.scrollTo(button);
      button.focus(); // scroll + focus, but do NOT seek
    }
  }

  // ---- keyboard-navigable preference ---------------------------------------

  private applyTabbable(): void {
    for (const button of this.cueButtons) {
      button.tabIndex = this.tabbable ? 0 : -1;
    }
  }

  private readTabbablePreference(): boolean {
    try {
      return window.localStorage.getItem(TABBABLE_STORAGE_KEY) === "true";
    } catch {
      return false;
    }
  }

  private writeTabbablePreference(value: boolean): void {
    try {
      window.localStorage.setItem(TABBABLE_STORAGE_KEY, value ? "true" : "false");
    } catch {
      // storage unavailable — preference simply won't persist
    }
  }
}

export const CAST_TRANSCRIPT_TAG = "cast-transcript";

export function defineCastTranscript(): void {
  if (!customElements.get(CAST_TRANSCRIPT_TAG)) {
    customElements.define(CAST_TRANSCRIPT_TAG, CastTranscriptElement);
  }
}
