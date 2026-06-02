// <cast-chapters for="..." data-mode="list|current"> — renders the chapter list
// (each a seek button) or a compact current-chapter indicator, and tracks the
// current chapter from the controller.

import { AudioController } from "./audio-controller";
import { formatTime } from "./format";
import { CastPlayerView } from "./view-base";

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
      this.renderCurrent(controller);
    } else {
      this.renderList(controller);
    }
    this.listen("chapterchange", () => this.updateActive(controller.currentChapterIndex));
    this.updateActive(controller.currentChapterIndex);
  }

  private renderList(controller: AudioController): void {
    const list = document.createElement("ol");
    list.className = "cast-chapters__list";
    this.buttons = [];
    controller.getChapters().forEach((chapter, index) => {
      const item = document.createElement("li");
      item.className = "cast-chapters__item";
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
    this.appendChild(list);
  }

  private renderCurrent(controller: AudioController): void {
    const label = document.createElement("p");
    label.className = "cast-chapters__current";
    this.currentLabel = label;
    this.appendChild(label);
    void controller;
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
