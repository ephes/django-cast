// <cast-chapters for="..." data-mode="list|current"> — a collapsible chapter
// list (each a seek button, timestamp + title) or a compact current-chapter
// indicator, tracking the current chapter from the controller.

import { AudioController } from "./audio-controller";
import { formatTime } from "./format";
import { CastPlayerView } from "./view-base";

const CHEVRON =
  '<svg class="cast-panel__chevron" width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5l8 7-8 7z"/></svg>';

const OPEN_STORAGE_KEY = "cast-chapters-open";

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

export class CastChaptersElement extends CastPlayerView {
  private buttons: HTMLButtonElement[] = [];
  private currentLabel?: HTMLElement;
  private section?: HTMLElement;
  private body?: HTMLElement;
  private toggleBtn?: HTMLButtonElement;

  protected onController(controller: AudioController): void {
    const chapters = controller.getChapters();
    if (chapters.length === 0) {
      return; // render nothing — no empty box, no layout shift
    }
    const mode = this.getAttribute("data-mode") === "current" ? "current" : "list";
    if (mode === "current") {
      this.renderCurrent();
    } else {
      this.renderList(controller);
    }
    this.listen("chapterchange", () => this.updateActive(controller.currentChapterIndex));
    // Accordion: collapse when the sibling transcript panel opens.
    this.listen("castpanelopen", (event) => {
      const detail = (event as CustomEvent<{ kind: string }>).detail;
      if (detail && detail.kind !== "chapters" && this.section?.classList.contains("is-open")) {
        this.setOpen(false);
      }
    });
    this.updateActive(controller.currentChapterIndex);
  }

  private setOpen(open: boolean): void {
    if (!this.section || !this.toggleBtn || !this.body) {
      return;
    }
    this.section.classList.toggle("is-open", open);
    this.toggleBtn.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) {
      this.body.removeAttribute("inert");
      // Accordion: tell the sibling transcript panel to collapse.
      this.controller?.dispatchEvent(new CustomEvent("castpanelopen", { detail: { kind: "chapters" } }));
    } else {
      this.body.setAttribute("inert", "");
    }
    writeBool(OPEN_STORAGE_KEY, open);
  }

  private renderList(controller: AudioController): void {
    const open = readBool(OPEN_STORAGE_KEY, false);
    const section = document.createElement("section");
    section.className = open ? "cast-chapters cast-panel is-open" : "cast-chapters cast-panel";
    section.setAttribute("aria-label", "Chapters");

    const header = document.createElement("div");
    header.className = "cast-panel__header";
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "cast-panel__toggle";
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    toggle.innerHTML = CHEVRON;
    const label = document.createElement("span");
    label.textContent = "Chapters";
    const count = document.createElement("span");
    count.className = "cast-panel__count";
    count.textContent = `${controller.getChapters().length}`;
    toggle.append(label, count);
    header.appendChild(toggle);

    const body = document.createElement("div");
    body.className = "cast-panel__body";
    const scroll = document.createElement("div");
    scroll.className = "cast-panel__scroll";
    const list = document.createElement("ol");
    list.className = "cast-chapters__list";

    this.buttons = [];
    controller.getChapters().forEach((chapter, index) => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "cast-chapters__button";

      const time = document.createElement("span");
      time.className = "cast-chapters__time";
      time.textContent = formatTime(chapter.start);

      const title = document.createElement("span");
      title.className = "cast-chapters__title";
      title.textContent = chapter.title;

      button.append(time, title);
      button.addEventListener("click", () => controller.seekToChapter(index));
      item.appendChild(button);
      list.appendChild(item);
      this.buttons.push(button);
    });

    scroll.appendChild(list);
    body.appendChild(scroll);
    // Collapsed by default (a compact pill); collapsing marks the body inert so
    // the chapter buttons leave the tab order. The open state is persisted.
    if (!open) {
      body.setAttribute("inert", "");
    }
    this.section = section;
    this.body = body;
    this.toggleBtn = toggle;
    toggle.addEventListener("click", () => this.setOpen(!section.classList.contains("is-open")));
    section.append(header, body);
    this.appendChild(section);
  }

  private renderCurrent(): void {
    const label = document.createElement("p");
    label.className = "cast-chapters__current";
    this.currentLabel = label;
    this.appendChild(label);
  }

  private updateActive(index: number): void {
    if (this.currentLabel) {
      const chapter = this.controller?.getChapters()[index];
      this.currentLabel.textContent = chapter ? chapter.title : "";
      return;
    }
    this.buttons.forEach((button, i) => {
      if (i === index) {
        button.setAttribute("aria-current", "true");
        button.classList.add("is-current");
      } else {
        button.removeAttribute("aria-current");
        button.classList.remove("is-current");
      }
    });
  }
}

export const CAST_CHAPTERS_TAG = "cast-chapters";

export function defineCastChapters(): void {
  if (!customElements.get(CAST_CHAPTERS_TAG)) {
    customElements.define(CAST_CHAPTERS_TAG, CastChaptersElement);
  }
}
