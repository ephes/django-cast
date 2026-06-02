// <cast-chapters for="..." data-mode="list|current"> — a collapsible chapter
// list (each a seek button, timestamp + title) or a compact current-chapter
// indicator, tracking the current chapter from the controller.

import { AudioController } from "./audio-controller";
import { formatTime } from "./format";
import { CastPlayerView } from "./view-base";

const CHEVRON =
  '<svg class="cast-panel__chevron" width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5l8 7-8 7z"/></svg>';

export class CastChaptersElement extends CastPlayerView {
  private buttons: HTMLButtonElement[] = [];
  private currentLabel?: HTMLElement;

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
    this.updateActive(controller.currentChapterIndex);
  }

  private renderList(controller: AudioController): void {
    const section = document.createElement("section");
    section.className = "cast-chapters cast-panel is-open";
    section.setAttribute("aria-label", "Chapters");

    const header = document.createElement("div");
    header.className = "cast-panel__header";
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "cast-panel__toggle";
    toggle.setAttribute("aria-expanded", "true");
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
    // Default open; collapsing marks the body inert so collapsed chapter buttons
    // leave the tab order.
    toggle.addEventListener("click", () => {
      const open = section.classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      if (open) {
        body.removeAttribute("inert");
      } else {
        body.setAttribute("inert", "");
      }
    });
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
