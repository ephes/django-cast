import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

function renderInlineRow(contributorId = "1", selectedLinkId = "", includeOptionsUrl = false) {
  document.body.innerHTML = `
    <div id="inline_child_contributor_assignments-0" data-inline-panel-child>
      <input type="hidden" name="contributor_assignments-0-contributor" value="${contributorId}" />
      <select data-cast-contributor-link-select="true"${
        includeOptionsUrl ? ' data-cast-contributor-link-options-url="/cms/contributors/links/"' : ""
      } name="contributor_assignments-0-link">
        <option value="">---------</option>
        <option value="11" data-cast-contributor-id="1"${
          selectedLinkId === "11" ? " selected" : ""
        }>Jochen: Mastodon</option>
        <option value="22" data-cast-contributor-id="2"${
          selectedLinkId === "22" ? " selected" : ""
        }>Mira: Website</option>
      </select>
    </div>
  `;
}

function linkSelect() {
  return document.querySelector("select") as HTMLSelectElement;
}

function contributorInput() {
  return document.querySelector('input[name$="-contributor"]') as HTMLInputElement;
}

function optionTexts(select = linkSelect()) {
  return Array.from(select.options).map((option) => option.textContent);
}

function initContributorLinkSelects(root: Document | Element = document) {
  root.dispatchEvent(new CustomEvent("w-formset:ready", { bubbles: true }));
}

async function flushPromises() {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

function deferredResponse(links: Array<{ contributorId: string; text: string; value: string }>) {
  let resolve: (response: { ok: true; json: () => Promise<{ links: typeof links }> }) => void = () => {};
  const promise = new Promise<{ ok: true; json: () => Promise<{ links: typeof links }> }>((promiseResolve) => {
    resolve = promiseResolve;
  });
  return {
    promise,
    resolve: () =>
      resolve({
        ok: true,
        json: () => Promise.resolve({ links }),
      }),
  };
}

describe("contributor-link-select", () => {
  beforeAll(async () => {
    Object.defineProperty(document, "readyState", { configurable: true, value: "complete" });
    await import("../../../src/cast/static/cast/js/wagtail/contributor-link-select.js");
  });

  beforeEach(() => {
    document.body.innerHTML = "";
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("filters links to the initially selected contributor", () => {
    renderInlineRow("1");

    initContributorLinkSelects();

    expect(optionTexts()).toEqual(["---------", "Jochen: Mastodon"]);
    expect(linkSelect().disabled).toBe(false);
  });

  it("updates the link choices when the contributor chooser value changes", () => {
    renderInlineRow("1");
    initContributorLinkSelects();

    contributorInput().value = "2";
    contributorInput().dispatchEvent(new Event("change", { bubbles: true }));

    expect(optionTexts()).toEqual(["---------", "Mira: Website"]);
  });

  it("loads links for a contributor that was created after the form rendered", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({
        links: [{ contributorId: "3", text: "Nora: Website", value: "33" }],
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    renderInlineRow("1", "", true);
    initContributorLinkSelects();

    contributorInput().value = "3";
    contributorInput().dispatchEvent(new Event("change", { bubbles: true }));

    expect(linkSelect().disabled).toBe(true);

    await flushPromises();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toContain("/cms/contributors/links/?contributor_id=3");
    expect(optionTexts()).toEqual(["---------", "Nora: Website"]);
    expect(linkSelect().disabled).toBe(false);
  });

  it("ignores stale fetch completions when the contributor changes again", async () => {
    const firstRequest = deferredResponse([{ contributorId: "3", text: "Nora: Website", value: "33" }]);
    const secondRequest = deferredResponse([{ contributorId: "4", text: "Ola: Website", value: "44" }]);
    const fetchMock = vi.fn().mockReturnValueOnce(firstRequest.promise).mockReturnValueOnce(secondRequest.promise);
    vi.stubGlobal("fetch", fetchMock);
    renderInlineRow("1", "", true);
    initContributorLinkSelects();

    contributorInput().value = "3";
    contributorInput().dispatchEvent(new Event("change", { bubbles: true }));
    contributorInput().value = "4";
    contributorInput().dispatchEvent(new Event("change", { bubbles: true }));

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(linkSelect().disabled).toBe(true);

    firstRequest.resolve();
    await flushPromises();

    expect(optionTexts()).toEqual(["---------"]);
    expect(linkSelect().disabled).toBe(true);

    secondRequest.resolve();
    await flushPromises();

    expect(optionTexts()).toEqual(["---------", "Ola: Website"]);
    expect(linkSelect().disabled).toBe(false);
  });

  it("clears an already selected link when it belongs to the previous contributor", () => {
    renderInlineRow("1", "11");
    initContributorLinkSelects();

    const select = linkSelect();
    let changeEvents = 0;
    select.addEventListener("change", () => {
      changeEvents += 1;
    });
    contributorInput().value = "2";
    contributorInput().dispatchEvent(new Event("change", { bubbles: true }));

    expect(select.value).toBe("");
    expect(changeEvents).toBe(1);
  });

  it("disables the link select until a contributor is selected", () => {
    renderInlineRow("");

    initContributorLinkSelects();

    expect(optionTexts()).toEqual(["---------"]);
    expect(linkSelect().disabled).toBe(true);
  });

  it("initializes newly added Wagtail inline rows", () => {
    renderInlineRow("2");
    const row = document.querySelector("[data-inline-panel-child]") as HTMLElement;

    row.dispatchEvent(new CustomEvent("w-formset:added", { bubbles: true }));

    expect(optionTexts()).toEqual(["---------", "Mira: Website"]);
  });
});
