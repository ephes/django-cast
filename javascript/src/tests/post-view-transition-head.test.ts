import { afterEach, describe, expect, it, vi } from "vitest";

// The render-blocking part of post-view-transition.js runs once when the
// script executes in the <head>, so every case imports a fresh module copy.
const STORAGE_KEY = "cast-post-view-transition";
const ORIGIN = window.location.origin;

afterEach(() => vi.unstubAllGlobals());

async function loadScriptAt(path: string, handoff: string | null, entryId?: string) {
  vi.stubGlobal("navigation", entryId ? { currentEntry: { id: entryId } } : undefined);
  document.head.innerHTML = "";
  window.history.replaceState(null, "", path);
  window.sessionStorage.clear();
  if (handoff !== null) {
    window.sessionStorage.setItem(STORAGE_KEY, handoff);
  }
  vi.resetModules();
  await import("../../../src/cast/static/cast/js/post-view-transition.js");
  return Array.from(document.head.querySelectorAll<HTMLLinkElement>('link[rel="expect"]'));
}

describe("post-view-transition render blocking", () => {
  it("blocks rendering until parsed when a handoff targets this page", async () => {
    const links = await loadScriptAt(
      "/blog/first/",
      JSON.stringify({ post: `${ORIGIN}/blog/first/`, to: `${ORIGIN}/blog/first/`, createdAt: Date.now() }),
    );

    expect(links).toHaveLength(1);
    expect(links[0].getAttribute("blocking")).toBe("render");
    expect(links[0].getAttribute("href")).toBe("#cast-post-view-transition-parsed");
    expect(document.getElementById("cast-post-view-transition-parsed")).toBeNull();
    // The handoff stays for the pagereveal handler.
    expect(window.sessionStorage.getItem(STORAGE_KEY)).not.toBeNull();
  });

  it.each([
    ["/blog/first/?variant=b", "target-entry", 0],
    ["/blog/first/", "other-entry", 0],
    ["/blog/first/", "target-entry", 60_000],
  ])("skips a stale handoff at %s with entry %s and age %s", async (path, entryId, age) => {
    const handoff = JSON.stringify({
      post: `${ORIGIN}/blog/first/`,
      to: path.includes("?") ? `${ORIGIN}/blog/first/?variant=a` : `${ORIGIN}/blog/first/`,
      entryId: "target-entry",
      createdAt: Date.now() - age,
    });

    expect(await loadScriptAt(path, handoff, entryId)).toHaveLength(0);
  });

  it("does not block rendering without a handoff for this page", async () => {
    expect(await loadScriptAt("/blog/first/", null)).toHaveLength(0);
    expect(
      await loadScriptAt("/blog/", JSON.stringify({ post: `${ORIGIN}/blog/first/`, to: `${ORIGIN}/blog/first/`, createdAt: Date.now() })),
    ).toHaveLength(0);
    expect(await loadScriptAt("/blog/first/", "{not json")).toHaveLength(0);
    // Proves each load re-executes the script rather than reusing a cached copy.
    expect(
      await loadScriptAt("/blog/", JSON.stringify({ post: `${ORIGIN}/blog/first/`, to: `${ORIGIN}/blog/`, createdAt: Date.now() })),
    ).toHaveLength(1);
  });
});
