import { beforeAll, beforeEach, describe, expect, it } from "vitest";

function renderInlineRow(contributorId = "1", selectedLinkId = "") {
  document.body.innerHTML = `
    <div id="inline_child_contributor_assignments-0" data-inline-panel-child>
      <input type="hidden" name="contributor_assignments-0-contributor" value="${contributorId}" />
      <select data-cast-contributor-link-select="true" name="contributor_assignments-0-link">
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

describe("contributor-link-select", () => {
  beforeAll(async () => {
    Object.defineProperty(document, "readyState", { configurable: true, value: "complete" });
    await import("../../../src/cast/static/cast/js/wagtail/contributor-link-select.js");
  });

  beforeEach(() => {
    document.body.innerHTML = "";
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
