import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Exercise the shipped inline script directly; no duplicate implementation.
const template = readFileSync(resolve(process.cwd(), "../src/cast/templates/cast/wagtail/_transcript_status_poll.html"), "utf8");
const script = template.replace(/<\/?script>/g, "");
const active = {transcript_generation_active: true, transcript_generation_message: "Running", transcript_generation_error: "", transcript_generation_transcript_url: ""};
function mount(isActive = true) {
  document.body.innerHTML = `<div data-active="${isActive}" data-status-url="/status/" data-poll-error="Reload the page"><p data-generation-message></p><p data-generation-error></p><a data-generation-link hidden>Name the voices</a></div><script></script>`;
  Object.defineProperty(document, "currentScript", {configurable: true, value: document.querySelector("script")});
  new Function(script)();
}

describe("transcript status polling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01"));
    Object.defineProperty(document, "hidden", {configurable: true, value: false});
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ok: true, json: async () => active}));
  });
  afterEach(() => {
    Object.defineProperty(document, "hidden", {configurable: true, value: true});
    document.dispatchEvent(new Event("visibilitychange"));
    vi.useRealTimers();
    vi.unstubAllGlobals();
    document.body.innerHTML = "";
  });
  it("updates status and ends with a link", async () => {
    mount();
    await vi.advanceTimersByTimeAsync(5000);
    expect(document.querySelector("[data-generation-message]")?.textContent).toBe("Running");
    vi.mocked(fetch).mockResolvedValueOnce({ok: true, json: async () => ({...active, transcript_generation_active: false, transcript_generation_message: "Completed", transcript_generation_transcript_url: "/edit/"})} as Response);
    await vi.advanceTimersByTimeAsync(5000);
    expect(document.querySelector<HTMLAnchorElement>("a")?.hidden).toBe(false);
    expect(document.querySelector("a")?.getAttribute("href")).toBe("/edit/");
    await vi.advanceTimersByTimeAsync(60000);
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it("ends on failed generation and displays its message", async () => {
    vi.mocked(fetch).mockResolvedValue({ok: true, json: async () => ({...active, transcript_generation_active: false, transcript_generation_error: "Failed upstream"})} as Response);
    mount();
    await vi.advanceTimersByTimeAsync(15000);
    expect(document.querySelector("[data-generation-error]")?.textContent).toBe("Failed upstream");
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it("stops on request failure", async () => {
    vi.mocked(fetch).mockResolvedValue({ok: false} as Response);
    mount();
    await vi.advanceTimersByTimeAsync(15000);
    expect(document.querySelector("[data-generation-error]")?.textContent).toBe("Reload the page");
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it("does not start for a finished run or a hidden tab", async () => {
    mount(false);
    await vi.advanceTimersByTimeAsync(10000);
    Object.defineProperty(document, "hidden", {configurable: true, value: true});
    mount();
    await vi.advanceTimersByTimeAsync(10000);
    expect(fetch).not.toHaveBeenCalled();
  });
  it("stops when the tab is hidden", async () => {
    mount();
    await vi.advanceTimersByTimeAsync(5000);
    Object.defineProperty(document, "hidden", {configurable: true, value: true});
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(60000);
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it("ignores a pending response after the tab is hidden", async () => {
    let respond!: (value: Response) => void;
    vi.mocked(fetch).mockImplementation(() => new Promise(resolve => { respond = resolve; }));
    mount();
    await vi.advanceTimersByTimeAsync(5000);
    Object.defineProperty(document, "hidden", {configurable: true, value: true});
    document.dispatchEvent(new Event("visibilitychange"));
    respond({ok: true, json: async () => active} as Response);
    await vi.advanceTimersByTimeAsync(5000);
    expect(document.querySelector("[data-generation-message]")?.textContent).toBe("");
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it("stops at thirty minutes", async () => {
    mount();
    await vi.advanceTimersByTimeAsync(30 * 60 * 1000);
    const calls = vi.mocked(fetch).mock.calls.length;
    expect(calls).toBe(359);
    await vi.advanceTimersByTimeAsync(60000);
    expect(fetch).toHaveBeenCalledTimes(calls);
  });
});
