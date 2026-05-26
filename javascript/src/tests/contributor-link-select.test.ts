import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

type RenderInlineRowOptions = {
  includeOptionsUrl?: boolean;
  rowId?: string;
  selectedRole?: string;
};

function renderInlineRow(
  contributorId = "1",
  selectedLinkId = "",
  includeOptionsOrConfig: boolean | RenderInlineRowOptions = false,
) {
  const config: RenderInlineRowOptions =
    typeof includeOptionsOrConfig === "boolean"
      ? { includeOptionsUrl: includeOptionsOrConfig }
      : includeOptionsOrConfig;
  const includeOptionsUrl = config.includeOptionsUrl || false;
  const rowId = config.rowId ?? "saved-assignment";
  const selectedRole = config.selectedRole || "guest";

  document.body.innerHTML = `
    <div id="inline_child_contributor_assignments-0" data-inline-panel-child>
      <input type="hidden" name="contributor_assignments-0-contributor" value="${contributorId}" />
      <input type="hidden" name="contributor_assignments-0-id" value="${rowId}" />
      <select name="contributor_assignments-0-role">
        <option value="host"${selectedRole === "host" ? " selected" : ""}>Host</option>
        <option value="guest"${selectedRole === "guest" ? " selected" : ""}>Guest</option>
      </select>
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
  return document.querySelector("select[data-cast-contributor-link-select]") as HTMLSelectElement;
}

function contributorInput() {
  return document.querySelector('input[name$="-contributor"]') as HTMLInputElement;
}

function roleSelect() {
  return document.querySelector('select[name$="-role"]') as HTMLSelectElement;
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
  type LinkResponse = {
    defaultLinkId: string;
    defaultRole: string;
    links: typeof links;
  };
  let resolve: (response: { ok: true; json: () => Promise<LinkResponse> }) => void = () => {};
  const promise = new Promise<{ ok: true; json: () => Promise<LinkResponse> }>((promiseResolve) => {
    resolve = promiseResolve;
  });
  return {
    promise,
    resolve: (overrides: Partial<LinkResponse> = {}) =>
      resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            defaultLinkId: links[0]?.value || "",
            defaultRole: "",
            links,
            ...overrides,
          }),
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
    expect(linkSelect().value).toBe("");
  });

  it("updates the link choices when the contributor chooser value changes", () => {
    renderInlineRow("1");
    initContributorLinkSelects();

    contributorInput().value = "2";
    contributorInput().dispatchEvent(new Event("change", { bubbles: true }));

    expect(optionTexts()).toEqual(["---------", "Mira: Website"]);
    expect(linkSelect().value).toBe("22");
  });

  it("loads links for a contributor that was created after the form rendered", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({
        defaultLinkId: "33",
        defaultRole: "",
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
    expect(linkSelect().value).toBe("33");
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
    expect(linkSelect().value).toBe("44");
    expect(linkSelect().disabled).toBe(false);
  });

  it("replaces an already selected link when it belongs to the previous contributor", () => {
    renderInlineRow("1", "11");
    initContributorLinkSelects();

    const select = linkSelect();
    let changeEvents = 0;
    select.addEventListener("change", () => {
      changeEvents += 1;
    });
    contributorInput().value = "2";
    contributorInput().dispatchEvent(new Event("change", { bubbles: true }));

    expect(select.value).toBe("22");
    expect(changeEvents).toBe(2);
  });

  it("disables the link select until a contributor is selected", () => {
    renderInlineRow("");

    initContributorLinkSelects();

    expect(optionTexts()).toEqual(["---------"]);
    expect(linkSelect().disabled).toBe(true);
  });

  it("fills contributor defaults when a contributor is selected", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({
        defaultLinkId: "22",
        defaultRole: "host",
        links: [],
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    renderInlineRow("1", "", { includeOptionsUrl: true });
    initContributorLinkSelects();
    let roleChangeEvents = 0;
    let linkChangeEvents = 0;
    roleSelect().addEventListener("change", () => {
      roleChangeEvents += 1;
    });
    linkSelect().addEventListener("change", () => {
      linkChangeEvents += 1;
    });

    contributorInput().value = "2";
    contributorInput().dispatchEvent(new Event("change", { bubbles: true }));

    expect(linkSelect().value).toBe("");
    expect(roleSelect().value).toBe("guest");

    await flushPromises();

    expect(roleSelect().value).toBe("host");
    expect(linkSelect().value).toBe("22");
    expect(roleChangeEvents).toBe(1);
    expect(linkChangeEvents).toBe(1);
  });

  it("does not overwrite a manually changed role when contributor defaults load", async () => {
    const response = deferredResponse([]);
    const fetchMock = vi.fn().mockReturnValue(response.promise);
    vi.stubGlobal("fetch", fetchMock);
    renderInlineRow("1", "", { includeOptionsUrl: true });
    initContributorLinkSelects();

    contributorInput().value = "2";
    contributorInput().dispatchEvent(new Event("change", { bubbles: true }));
    roleSelect().value = "host";
    roleSelect().dispatchEvent(new Event("change", { bubbles: true }));

    response.resolve({
      defaultLinkId: "22",
      defaultRole: "guest",
      links: [],
    });
    await flushPromises();

    expect(roleSelect().value).toBe("host");
  });

  it("uses the new contributor default role after an earlier manual role change", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue({
          defaultLinkId: "22",
          defaultRole: "host",
          links: [],
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue({
          defaultLinkId: "33",
          defaultRole: "host",
          links: [{ contributorId: "3", text: "Nora: Website", value: "33" }],
        }),
      });
    vi.stubGlobal("fetch", fetchMock);
    renderInlineRow("1", "", { includeOptionsUrl: true });
    initContributorLinkSelects();

    contributorInput().value = "2";
    contributorInput().dispatchEvent(new Event("change", { bubbles: true }));

    await flushPromises();

    expect(roleSelect().value).toBe("host");

    roleSelect().value = "guest";
    roleSelect().dispatchEvent(new Event("change", { bubbles: true }));
    contributorInput().value = "3";
    contributorInput().dispatchEvent(new Event("change", { bubbles: true }));

    await flushPromises();

    expect(roleSelect().value).toBe("host");
    expect(linkSelect().value).toBe("33");
  });

  it("fills defaults on init for an unsaved row with a preselected contributor", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({
        defaultLinkId: "11",
        defaultRole: "host",
        links: [],
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    renderInlineRow("1", "", { includeOptionsUrl: true, rowId: "" });

    initContributorLinkSelects();

    expect(linkSelect().value).toBe("");

    await flushPromises();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(roleSelect().value).toBe("host");
    expect(linkSelect().value).toBe("11");
  });

  it("initializes newly added Wagtail inline rows", () => {
    renderInlineRow("2");
    const row = document.querySelector("[data-inline-panel-child]") as HTMLElement;

    row.dispatchEvent(new CustomEvent("w-formset:added", { bubbles: true }));

    expect(optionTexts()).toEqual(["---------", "Mira: Website"]);
  });
});
