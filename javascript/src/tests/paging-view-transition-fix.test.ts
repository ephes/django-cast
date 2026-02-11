import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

describe("paging-view-transition-fix", () => {
  beforeAll(async () => {
    await import("../../../src/cast/static/cast/js/paging-view-transition-fix.js");
  });

  beforeEach(() => {
    document.body.innerHTML = '<div id="paging-area"></div><div id="other-area"></div>';
    vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("scrolls to top before transition when detail.target is #paging-area", () => {
    const pagingArea = document.querySelector("#paging-area") as HTMLElement;

    document.dispatchEvent(new CustomEvent("htmx:beforeTransition", { detail: { target: pagingArea } }));

    expect(window.scrollTo).toHaveBeenCalledWith(0, 0);
  });

  it("does not scroll for unrelated transition targets", () => {
    const otherArea = document.querySelector("#other-area") as HTMLElement;

    document.dispatchEvent(new CustomEvent("htmx:beforeTransition", { detail: { target: otherArea } }));

    expect(window.scrollTo).not.toHaveBeenCalled();
  });

  it("scrolls to top before transition when detail.elt is #paging-area", () => {
    const pagingArea = document.querySelector("#paging-area") as HTMLElement;

    document.dispatchEvent(new CustomEvent("htmx:beforeTransition", { detail: { elt: pagingArea } }));

    expect(window.scrollTo).toHaveBeenCalledWith(0, 0);
  });

  it("skips transition instead of scrolling when already far down the page", () => {
    const pagingArea = document.querySelector("#paging-area") as HTMLElement;
    Object.defineProperty(window, "scrollY", { configurable: true, value: 500 });
    const event = new CustomEvent("htmx:beforeTransition", {
      cancelable: true,
      detail: { target: pagingArea },
    });

    document.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(true);
    expect(window.scrollTo).not.toHaveBeenCalled();
  });
});
