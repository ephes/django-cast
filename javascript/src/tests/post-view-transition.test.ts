import { afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";

const STORAGE_KEY = "cast-post-view-transition";
const ORIGIN = window.location.origin;

function article(slug: string, withImage = true): string {
  const image = withImage ? '<section class="block-image"><img src="/image.jpg"></section>' : "";
  return `<article>
    <header><h2><a href="/blog/${slug}/">${slug}</a></h2><a href="/blog/${slug}/"><time>date</time></a></header>
    <section class="block-overview">${image}</section>
  </article>`;
}

function fakeTransition(types: string[] = ["cast-page"]) {
  let finish: () => void = () => {};
  const finished = new Promise<void>((resolve) => {
    finish = resolve;
  });
  return { viewTransition: { types: new Set(types), finished }, finish };
}

function dispatchPageSwap(viewTransition: object | null, url: string | null) {
  const event = new Event("pageswap");
  Object.assign(event, { viewTransition, activation: url ? { entry: { url } } : null });
  window.dispatchEvent(event);
}

function dispatchPageReveal(viewTransition: object | null) {
  const event = new Event("pagereveal");
  Object.assign(event, { viewTransition });
  window.dispatchEvent(event);
}

function namedElements(): string[] {
  return Array.from(document.querySelectorAll<HTMLElement>("h2, img"))
    .filter((element) => element.style.viewTransitionName)
    .map((element) => `${element.tagName}:${element.style.viewTransitionName}`);
}

function setLocation(path: string) {
  window.history.replaceState(null, "", path);
}

describe("post-view-transition", () => {
  beforeAll(async () => {
    await import("../../../src/cast/static/cast/js/post-view-transition.js");
  });

  beforeEach(() => {
    window.sessionStorage.clear();
  });

  afterEach(() => {
    document.body.innerHTML = "";
    setLocation("/");
  });

  describe("pageswap", () => {
    it("names the opened post's title and first overview image on a list page", async () => {
      setLocation("/blog/");
      document.body.innerHTML = `<div id="paging-area">${article("first")}${article("second")}</div>`;
      const { viewTransition, finish } = fakeTransition();

      dispatchPageSwap(viewTransition, `${ORIGIN}/blog/second/?utm=x`);

      const second = document.querySelectorAll("article")[1];
      expect(second.querySelector("h2")?.style.viewTransitionName).toBe("cast-post-title");
      expect(second.querySelector("img")?.style.viewTransitionName).toBe("cast-post-image");
      expect(namedElements()).toHaveLength(2);
      expect(JSON.parse(window.sessionStorage.getItem(STORAGE_KEY) ?? "null")).toEqual({
        post: `${ORIGIN}/blog/second/`,
        to: `${ORIGIN}/blog/second/`,
      });

      finish();
      await viewTransition.finished;
      await Promise.resolve();
      expect(namedElements()).toEqual([]);
    });

    it("names the current post when leaving its detail page", () => {
      setLocation("/blog/first/");
      document.body.innerHTML = article("first");
      const { viewTransition } = fakeTransition();

      dispatchPageSwap(viewTransition, `${ORIGIN}/blog/`);

      expect(namedElements()).toEqual(["H2:cast-post-title", "IMG:cast-post-image"]);
      expect(JSON.parse(window.sessionStorage.getItem(STORAGE_KEY) ?? "null")).toEqual({
        post: `${ORIGIN}/blog/first/`,
        to: `${ORIGIN}/blog/`,
      });
    });

    it("finds posts whose heading is unlinked, as in the plain theme", () => {
      setLocation("/blog/");
      document.body.innerHTML = `<article>
        <header><h2>Plain post</h2><a href="/blog/plain/"><time>date</time></a></header>
        <section class="block-overview"><img src="/image.jpg"></section>
      </article>`;
      const { viewTransition } = fakeTransition();

      dispatchPageSwap(viewTransition, `${ORIGIN}/blog/plain/`);

      expect(namedElements()).toEqual(["H2:cast-post-title", "IMG:cast-post-image"]);
    });

    it("skips audio player cover images when choosing the post image", () => {
      setLocation("/blog/episode/");
      document.body.innerHTML = `<article>
        <header><h2><a href="/blog/episode/">Episode</a></h2></header>
        <section class="block-overview">
          <podlove-player><img class="podlove-facade-cover" src="/cover.jpg"></podlove-player>
          <cast-audio-player><img src="/poster.jpg"></cast-audio-player>
          <section class="block-image"><img class="cast-image" src="/image.jpg"></section>
        </section>
      </article>`;
      const { viewTransition } = fakeTransition();

      dispatchPageSwap(viewTransition, `${ORIGIN}/blog/`);

      expect(document.querySelector(".cast-image")?.getAttribute("style")).toContain("cast-post-image");
      expect(namedElements()).toEqual(["H2:cast-post-title", "IMG:cast-post-image"]);
      expect(document.querySelector(".podlove-facade-cover")?.getAttribute("style") ?? "").toBe("");
    });

    it("names only the title when the only overview image belongs to a player", () => {
      setLocation("/blog/episode/");
      document.body.innerHTML = `<article>
        <header><h2><a href="/blog/episode/">Episode</a></h2></header>
        <section class="block-overview"><podlove-player><img src="/cover.jpg"></podlove-player></section>
      </article>`;
      const { viewTransition } = fakeTransition();

      dispatchPageSwap(viewTransition, `${ORIGIN}/blog/`);

      expect(namedElements()).toEqual(["H2:cast-post-title"]);
    });

    it("names only the title when the post has no overview image", () => {
      setLocation("/blog/");
      document.body.innerHTML = article("first", false);
      const { viewTransition } = fakeTransition();

      dispatchPageSwap(viewTransition, `${ORIGIN}/blog/first/`);

      expect(namedElements()).toEqual(["H2:cast-post-title"]);
    });

    it("ignores navigations between pages without a shared post", () => {
      setLocation("/blog/");
      document.body.innerHTML = article("first");
      window.sessionStorage.setItem(STORAGE_KEY, "stale");
      const { viewTransition } = fakeTransition();

      dispatchPageSwap(viewTransition, `${ORIGIN}/blog/?page=2`);

      expect(namedElements()).toEqual([]);
      expect(window.sessionStorage.getItem(STORAGE_KEY)).toBeNull();
    });

    it("ignores transitions without the cast-page type or without a transition", () => {
      setLocation("/blog/");
      document.body.innerHTML = article("first");

      dispatchPageSwap(fakeTransition(["other"]).viewTransition, `${ORIGIN}/blog/first/`);
      dispatchPageSwap(null, `${ORIGIN}/blog/first/`);
      dispatchPageSwap(fakeTransition().viewTransition, null);

      expect(namedElements()).toEqual([]);
      expect(window.sessionStorage.getItem(STORAGE_KEY)).toBeNull();
    });
  });

  describe("pagereveal", () => {
    it("names the handed-off post on the destination page and clears the handoff", async () => {
      setLocation("/blog/");
      document.body.innerHTML = `<div id="paging-area">${article("first")}${article("second")}</div>`;
      window.sessionStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ post: `${ORIGIN}/blog/second/`, to: `${ORIGIN}/blog/` }),
      );
      const { viewTransition, finish } = fakeTransition();

      dispatchPageReveal(viewTransition);

      const second = document.querySelectorAll("article")[1];
      expect(second.querySelector("h2")?.style.viewTransitionName).toBe("cast-post-title");
      expect(namedElements()).toHaveLength(2);
      expect(window.sessionStorage.getItem(STORAGE_KEY)).toBeNull();

      finish();
      await viewTransition.finished;
      await Promise.resolve();
      expect(namedElements()).toEqual([]);
    });

    it("ignores a handoff meant for another destination", () => {
      setLocation("/blog/first/");
      document.body.innerHTML = article("first");
      window.sessionStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ post: `${ORIGIN}/blog/first/`, to: `${ORIGIN}/elsewhere/` }),
      );

      dispatchPageReveal(fakeTransition().viewTransition);

      expect(namedElements()).toEqual([]);
      expect(window.sessionStorage.getItem(STORAGE_KEY)).toBeNull();
    });

    it("ignores reveals without a cast-page transition, a handoff, or a matching post", () => {
      setLocation("/blog/first/");
      document.body.innerHTML = article("first");
      const handoff = JSON.stringify({ post: `${ORIGIN}/blog/first/`, to: `${ORIGIN}/blog/first/` });

      window.sessionStorage.setItem(STORAGE_KEY, handoff);
      dispatchPageReveal(null);
      dispatchPageReveal(fakeTransition().viewTransition);
      window.sessionStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ post: `${ORIGIN}/blog/missing/`, to: `${ORIGIN}/blog/first/` }),
      );
      dispatchPageReveal(fakeTransition().viewTransition);
      window.sessionStorage.setItem(STORAGE_KEY, "{not json");
      dispatchPageReveal(fakeTransition().viewTransition);

      expect(namedElements()).toEqual([]);
      expect(window.sessionStorage.getItem(STORAGE_KEY)).toBeNull();
    });
  });
});
