// <cast-transcript for="..."> — a collapsible, django-chat-style transcript:
// a timestamp column + speaker-labelled text, current-cue highlight with
// follow-along auto-scroll, click-to-seek, and search (visible match marks +
// scroll-to-match). Never fetches; it only reads controller cues (the player
// owns all fetching). Renders cue text via textContent only (XSS-safe).

import { AudioController } from "./audio-controller";
import { formatTime } from "./format";
import type { Cue } from "./types";
import { CastPlayerView } from "./view-base";

const OPEN_STORAGE_KEY = "cast-transcript-open";
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
    const cues = controller.getCues();
    if (cues.length === 0 && !controller.transcriptPending) {
      return; // render nothing
    }
    this.open = readBool(OPEN_STORAGE_KEY, false);
    this.follow = readBool(FOLLOW_STORAGE_KEY, true);
    this.tabbable = readBool(TABBABLE_STORAGE_KEY, false);
    this.build();
    if (cues.length === 0 && controller.transcriptPending) {
      this.showLoading();
    } else {
      this.renderCues(cues);
    }
    this.listen("cueschange", () => this.renderCues(controller.getCues()));
    this.listen("cuechange", () => this.setActive(controller.currentCueIndex));
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
    const count = document.createElement("span");
    count.className = "cast-panel__count";
    toggle.append(label, count);
    toggle.addEventListener("click", () => this.toggleOpen());
    this.toggleButton = toggle;
    this.countLabel = count;

    header.append(toggle, this.buildTools());

    const body = document.createElement("div");
    body.className = "cast-panel__body";
    const scroll = document.createElement("div");
    scroll.className = "cast-panel__scroll";
    const list = document.createElement("div");
    list.className = "cast-transcript__cues";
    scroll.appendChild(list);
    body.appendChild(scroll);
    this.panelBody = body;
    this.scroll = scroll;
    this.list = list;
    // A collapsed panel is only visually clipped; mark it inert so its buttons
    // are removed from the tab order and not interactive while hidden.
    this.applyInert();

    section.append(header, body, this.buildOptions());
    this.section = section;
    this.appendChild(section);
  }

  private buildTools(): HTMLElement {
    const tools = document.createElement("div");
    tools.className = "cast-panel__tools";

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

    tools.append(search, prev, next, status, follow);
    return tools;
  }

  private buildOptions(): HTMLElement {
    const label = document.createElement("label");
    label.className = "cast-transcript__options";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = this.tabbable;
    input.addEventListener("change", () => {
      this.tabbable = input.checked;
      writeBool(TABBABLE_STORAGE_KEY, this.tabbable);
      this.applyTabbable();
    });
    const text = document.createElement("span");
    text.textContent = " Keyboard-navigable cues";
    label.append(input, text);
    return label;
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

  // ---- open / follow toggles ------------------------------------------------

  private toggleOpen(): void {
    this.open = !this.open;
    this.section?.classList.toggle("is-open", this.open);
    this.toggleButton?.setAttribute("aria-expanded", this.open ? "true" : "false");
    this.applyInert();
    writeBool(OPEN_STORAGE_KEY, this.open);
    if (this.open && this.controller) {
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
    this.cueButtons = [];
    if (this.countLabel) {
      this.countLabel.textContent = cues.length ? `${cues.length} lines` : "";
    }

    let previousSpeaker = "";
    cues.forEach((cue, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "cast-transcript__cue";
      button.tabIndex = this.tabbable ? 0 : -1;
      button.dataset.start = String(cue.start);
      button.dataset.end = String(cue.end);

      const time = document.createElement("span");
      time.className = "cast-transcript__time";
      time.textContent = formatTime(cue.start);

      const line = document.createElement("span");
      line.className = "cast-transcript__line";
      if (cue.speaker && cue.speaker !== previousSpeaker) {
        const speaker = document.createElement("span");
        speaker.className = "cast-transcript__speaker";
        speaker.textContent = cue.speaker; // textContent only
        line.appendChild(speaker);
      }
      previousSpeaker = cue.speaker;

      const text = document.createElement("span");
      text.className = "cast-transcript__text";
      text.textContent = cue.text; // textContent only — never innerHTML
      line.appendChild(text);

      button.append(time, line);
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
