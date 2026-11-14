import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("ajaxcomments", () => {
  beforeEach(() => {
    // Each test re-imports the IIFE, which registers fresh document-level click
    // listeners. Swap in a clean <body> so listeners from previous imports don't
    // accumulate and fire duplicate handlers against the same mocked Response.
    document.body.replaceWith(document.createElement("body"));
    // JSDOM doesn't implement scrollTo; the script calls it via setTimeout.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (window as any).scrollTo = vi.fn();
    // Provide a real function so tests can `vi.spyOn(window, "fetch")`; the
    // submit-path tests overwrite this directly with their own mock.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (globalThis as any).fetch = (() => {
      throw new Error("fetch not mocked");
    }) as typeof fetch;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("posts via fetch and clears the form on success", async () => {
    document.body.innerHTML = `
      <div id="comments-1" class="comments empty"></div>
      <div id="comment-added-message-1" style="display:none"></div>
      <form class="js-comments-form" action="/ajax" id="comment-form-1">
        <input type="hidden" name="object_pk" value="1" />
        <textarea name="comment">hello</textarea>
        <button type="submit" name="post">Post</button>
      </form>
    `;

    const fetchMock = vi.fn(async (_url: string, options: RequestInit) => {
      const body = options.body as FormData;
      expect(body.get("comment")).toBe("hello");
      expect(body.get("preview")).toBeNull();
      return {
        json: async () => ({
          success: true,
          object_id: "1",
          parent_id: null,
          comment_id: "42",
          use_threadedcomments: false,
          html: `<div id="c42" class="comment">ok</div>`,
        }),
      } as Response;
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (globalThis as any).fetch = fetchMock;

    // Make sure the script initializes immediately in tests.
    Object.defineProperty(document, "readyState", { value: "complete", configurable: true });
    vi.resetModules();
    await import("../comments/ajaxcomments");

    const form = document.querySelector("form.js-comments-form") as HTMLFormElement;
    const button = form.querySelector('button[name="post"]') as HTMLButtonElement;

    const evt = new SubmitEvent("submit", { bubbles: true, cancelable: true, submitter: button });
    form.dispatchEvent(evt);

    await flush();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect((form.elements.namedItem("comment") as HTMLTextAreaElement).value).toBe("");
    expect(document.getElementById("comments-1")?.classList.contains("empty")).toBe(false);
    expect(document.getElementById("c42")).not.toBeNull();
  });

  it("adds preview=1 when submitting via the preview button", async () => {
    document.body.innerHTML = `
      <div id="comments-1" class="comments empty"></div>
      <form class="js-comments-form" action="/ajax" id="comment-form-1">
        <input type="hidden" name="object_pk" value="1" />
        <textarea name="comment">hello</textarea>
        <button type="submit" name="preview">Preview</button>
      </form>
    `;

    const fetchMock = vi.fn(async (_url: string, options: RequestInit) => {
      const body = options.body as FormData;
      expect(body.get("preview")).toBe("1");
      return {
        json: async () => ({
          success: true,
          object_id: "1",
          parent_id: null,
          comment_id: "42",
          use_threadedcomments: false,
          html: `<div class="comment">preview</div>`,
        }),
      } as Response;
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (globalThis as any).fetch = fetchMock;

    Object.defineProperty(document, "readyState", { value: "complete", configurable: true });
    vi.resetModules();
    await import("../comments/ajaxcomments");

    const form = document.querySelector("form.js-comments-form") as HTMLFormElement;
    const button = form.querySelector('button[name="preview"]') as HTMLButtonElement;

    const evt = new SubmitEvent("submit", { bubbles: true, cancelable: true, submitter: button });
    form.dispatchEvent(evt);

    await flush();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(document.querySelector(".comment-preview-area")).not.toBeNull();
  });

  // delete: confirm -> POST to data-delete-action -> remove #c{id}
  it("deletes a comment on confirm", async () => {
    document.body.innerHTML = `
      <form class="js-comments-form" data-object-id="7">
        <input type="hidden" name="csrfmiddlewaretoken" value="tok" />
      </form>
      <div class="comments" data-object-id="7">
        <div id="c5" class="comment-item">
          <div class="comment-text">hi</div>
          <a class="comment-delete-link" data-comment-id="5" data-delete-action="/comments/delete/ajax/">delete</a>
        </div>
      </div>`;
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const fetchMock = vi.spyOn(window, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ success: true, action: "delete", comment_id: "5" }), { status: 200 }),
    );
    vi.resetModules();
    await import("../comments/ajaxcomments"); // re-runs the IIFE/init() against the DOM above
    document.querySelector(".comment-delete-link")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await flush();
    expect(fetchMock).toHaveBeenCalledWith("/comments/delete/ajax/", expect.objectContaining({ method: "POST" }));
    expect(document.getElementById("c5")).toBeNull();
  });

  // edit: open inline editor, submit -> POST to data-edit-action -> swap #c{id} with returned html
  it("edits a comment inline and swaps in the returned html", async () => {
    document.body.innerHTML = `
      <form class="js-comments-form" data-object-id="7">
        <input type="hidden" name="csrfmiddlewaretoken" value="tok" />
      </form>
      <div class="comments" data-object-id="7">
        <div id="c5" class="comment-item">
          <div class="comment-text">old</div>
          <textarea class="comment-raw" data-revision="original-revision" hidden>old</textarea>
          <a class="comment-edit-link" data-comment-id="5" data-edit-action="/comments/edit/ajax/">edit</a>
        </div>
      </div>`;
    const fetchMock = vi.spyOn(window, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ success: true, action: "edit", comment_id: "5", is_public: true, edited: true,
          html: '<div id="c5" class="comment-item"><div class="comment-text">new</div></div>' }),
        { status: 200 },
      ),
    );
    vi.resetModules();
    await import("../comments/ajaxcomments"); // re-runs the IIFE/init() against the DOM above
    document.querySelector(".comment-edit-link")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    const textarea = document.querySelector("#c5 .comment-edit-form textarea") as HTMLTextAreaElement;
    expect(textarea.value).toBe("old");
    textarea.value = "new";
    document.querySelector("#c5 .comment-edit-save")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await flush();
    const body = (fetchMock.mock.calls[0][1] as RequestInit).body as FormData;
    expect(body.get("comment")).toBe("new");
    expect(body.get("comment_id")).toBe("5");
    expect(document.querySelector("#c5 .comment-text")!.textContent).toBe("new");
  });
  const boot = async () => {
    Object.defineProperty(document, "readyState", { value: "complete", configurable: true });
    vi.resetModules();
    await import("../comments/ajaxcomments");
  };
  const deferred = () => {
    let resolve!: (response: Response) => void;
    return { promise: new Promise<Response>((done) => { resolve = done; }), resolve: (response: Response) => resolve(response) };
  };
  const actionMarkup = () => {
    document.body.innerHTML = `<form class="js-comments-form" data-object-id="7"></form>
      <div class="comments" data-object-id="7"><div id="c5">
      <div class="comment-text">old</div><textarea class="comment-raw" data-revision="original-revision" hidden>old</textarea>
      <a class="comment-edit-link" data-comment-id="5" data-edit-action="/edit">Edit</a>
      <a class="comment-delete-link" data-comment-id="5" data-delete-action="/delete">Delete</a></div></div>`;
  };
  const success = () => new Response(JSON.stringify({success: true, revision: "saved-revision", object_id: "7", comment_id: "5",
    html: '<div id="c5"><div class="comment-text">saved</div></div>'}), {status: 200});
  const click = (selector: string) => document.querySelector<HTMLElement>(selector)!.click();

  it.each(["comment", "parent"])("preserves a newer posted draft when %s changes", async (changed) => {
    document.body.innerHTML = `<div id="comments-7" class="comments"></div>
      <form class="js-comments-form" action="/post"><input name="object_pk" value="7">
      <input name="parent" value="17"><textarea name="comment">submitted</textarea><button type="submit">Post</button></form>`;
    const pending = deferred();
    vi.spyOn(window, "fetch").mockReturnValue(pending.promise);
    await boot();
    const form = document.querySelector("form")!;
    form.dispatchEvent(new SubmitEvent("submit", {bubbles: true, cancelable: true}));
    const field = form.elements.namedItem(changed) as HTMLInputElement;
    field.value = changed === "parent" ? "18" : "newer draft";
    pending.resolve(success());
    await flush();
    expect(field.value).toBe(changed === "parent" ? "18" : "newer draft");
    expect((form.elements.namedItem(changed === "parent" ? "comment" : "parent") as HTMLInputElement).value)
      .toBe(changed === "parent" ? "" : "17");
    expect(document.querySelector("#c5")).not.toBeNull();
  });

  it("owns one inline save and keeps text typed during its acknowledgment", async () => {
    actionMarkup();
    const pending = deferred();
    const fetchMock = vi.spyOn(window, "fetch").mockReturnValueOnce(pending.promise).mockResolvedValue(success());
    await boot(); click(".comment-edit-link");
    const textarea = document.querySelector<HTMLTextAreaElement>(".comment-edit-textarea")!;
    textarea.value = "submitted";
    click(".comment-edit-save");
    document.querySelector(".comment-edit-save")!.dispatchEvent(new MouseEvent("click", {bubbles: true}));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    textarea.value = "newer draft";
    pending.resolve(success()); await flush();
    expect(textarea.isConnected).toBe(true);
    expect(textarea.value).toBe("newer draft");
    expect(document.querySelector('[role="status"]')?.textContent).toContain("newer changes");
    click(".comment-edit-save"); await flush();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect((fetchMock.mock.calls[1][1]?.body as FormData).get("revision")).toBe("saved-revision");
    expect((fetchMock.mock.calls[1][1]?.body as FormData).get("comment")).toBe("newer draft");
    expect(document.querySelector(".comment-edit-form")).toBeNull();
  });

  it("keeps a conflicting draft and shows current text before an explicit retry", async () => {
    actionMarkup();
    const fetchMock = vi.spyOn(window, "fetch").mockResolvedValueOnce(new Response(JSON.stringify({
      success: false, conflict: true, current_comment: "<b>Accepted text</b>", revision: "current-revision",
    }), {status: 409})).mockResolvedValue(success());
    await boot(); click(".comment-edit-link");
    const textarea = document.querySelector<HTMLTextAreaElement>(".comment-edit-textarea")!;
    textarea.value = "unsent draft";
    click(".comment-edit-save"); await flush();
    expect((fetchMock.mock.calls[0][1]?.body as FormData).get("revision")).toBe("original-revision");
    expect(textarea.value).toBe("unsent draft");
    expect(document.querySelector(".comment-edit-status")?.textContent).toContain("<b>Accepted text</b>");
    expect(document.querySelector(".comment-edit-status b")).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    click(".comment-edit-save"); await flush();
    expect((fetchMock.mock.calls[1][1]?.body as FormData).get("revision")).toBe("current-revision");
    expect((fetchMock.mock.calls[1][1]?.body as FormData).get("comment")).toBe("unsent draft");
  });

  it("ignores a cancelled editor's late save after a new editor opens", async () => {
    actionMarkup(); const pending = deferred();
    vi.spyOn(window, "fetch").mockReturnValue(pending.promise);
    await boot(); click(".comment-edit-link"); click(".comment-edit-save"); click(".comment-edit-cancel");
    click(".comment-edit-link");
    const textarea = document.querySelector<HTMLTextAreaElement>(".comment-edit-textarea")!;
    textarea.value = "replacement editor";
    pending.resolve(success()); await flush();
    expect(textarea.isConnected).toBe(true);
    expect(textarea.value).toBe("replacement editor");
    expect(document.querySelector(".comment-text")?.textContent).toBe("old");
  });

  it.each(["edit", "delete"])("recovers %s from network, malformed JSON and HTTP failure", async (action) => {
    actionMarkup(); vi.spyOn(window, "confirm").mockReturnValue(true);
    const fetchMock = vi.spyOn(window, "fetch")
      .mockRejectedValueOnce(new Error("synthetic private details"))
      .mockResolvedValueOnce(new Response("malformed", {status: 200}))
      .mockResolvedValueOnce(new Response("forbidden", {status: 403}))
      .mockResolvedValue(success());
    await boot();
    if (action === "edit") { click(".comment-edit-link"); document.querySelector<HTMLTextAreaElement>(".comment-edit-textarea")!.value = "draft"; }
    const control = action === "edit" ? ".comment-edit-save" : ".comment-delete-link";
    for (let i = 0; i < 3; i++) {
      click(control); await flush();
      expect(document.querySelector("#c5")).not.toBeNull();
      expect(document.querySelector('[role="status"]')?.textContent).toContain("Could not");
      expect(document.body.textContent).not.toContain("synthetic private details");
      if (action === "edit") expect(document.querySelector<HTMLTextAreaElement>(".comment-edit-textarea")!.value).toBe("draft");
    }
    click(control); await flush();
    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(action === "delete" ? document.querySelector("#c5") : document.querySelector(".comment-edit-form")).toBeNull();
  });

  it.each(["edit", "delete"])("bounds %s headers and body and permits retry", async (action) => {
    for (const phase of ["headers", "body"]) {
      document.body.replaceWith(document.createElement("body"));
      actionMarkup(); vi.spyOn(window, "confirm").mockReturnValue(true);
      vi.useFakeTimers();
      try {
        const never = new Promise<Response>(() => {});
        const fetchMock = vi.spyOn(window, "fetch").mockReset().mockReturnValueOnce(phase === "headers" ? never : Promise.resolve({ok: true, json: () => never} as unknown as Response))
          .mockResolvedValue(success());
        await boot();
        if (action === "edit") click(".comment-edit-link");
        const control = action === "edit" ? ".comment-edit-save" : ".comment-delete-link";
        click(control); await vi.advanceTimersByTimeAsync(15000);
        expect(document.querySelector('[role="status"]')?.textContent).toContain("Could not");
        expect(fetchMock.mock.calls[0][1]?.signal?.aborted).toBe(true);
        click(control); await vi.advanceTimersByTimeAsync(0);
        expect(fetchMock).toHaveBeenCalledTimes(2);
        expect(action === "delete" ? document.querySelector("#c5") : document.querySelector(".comment-edit-form")).toBeNull();
      } finally { vi.clearAllTimers(); vi.useRealTimers(); }
    }
  });

  it.each([false, true])("scopes threaded reply/cancel to its object, missing form=%s", async (missing) => {
    document.body.innerHTML = [1,2].map((id) => `<div id="comments-${id}" class="comments" data-object-id="${id}">
      <ul><li class="comment-preview">Preview ${id}</li><li class="comment-wrapper" id="thread-${id}">
      <a class="comment-reply-link" data-comment-id="${id}01">Reply</a></li></ul></div>
      <form class="js-comments-form" data-object-id="${id}"><input name="object_pk" value="${id}">
      <input name="parent" value=""><textarea name="comment">Draft ${id}</textarea>
      <a class="comment-cancel-reply-link">Cancel</a></form>`).join("");
    await boot();
    const forms = Array.from(document.querySelectorAll("form"));
    if (missing) forms[1].remove();
    click("#thread-2 .comment-reply-link");
    expect(forms[0].closest(".comments")).toBeNull();
    expect(document.querySelector("#comments-1 .comment-preview")).not.toBeNull();
    expect((forms[0].elements.namedItem("comment") as HTMLTextAreaElement).value).toBe("Draft 1");
    if (missing) return;
    expect(forms[1].parentElement?.id).toBe("thread-2");
    expect(new FormData(forms[1]).get("parent")).toBe("201");
    expect(new FormData(forms[1]).get("object_pk")).toBe("2");
    click("#thread-2 .comment-cancel-reply-link");
    expect(forms[1].parentElement?.id).toBe("comments-form-orig-position-2");
    expect(new FormData(forms[1]).get("parent")).toBe("");
  });

  it("keeps a newer draft when its acknowledged edit awaits moderation, without offering impossible retries", async () => {
    actionMarkup(); const pending = deferred();
    const fetchMock = vi.spyOn(window, "fetch").mockReturnValue(pending.promise);
    await boot(); click(".comment-edit-link"); click(".comment-edit-save");
    const textarea = document.querySelector<HTMLTextAreaElement>(".comment-edit-textarea")!;
    textarea.value = "newer unsaved draft";
    pending.resolve(new Response(JSON.stringify({success: true, is_public: false,
      html: '<div id="c5"><div class="comment-text">moderated edit</div></div>'}), {status: 200}));
    await flush();
    expect(textarea.isConnected).toBe(true);
    expect(textarea.value).toBe("newer unsaved draft");
    expect(document.body.textContent).toContain("awaiting moderation");
    expect(document.body.textContent).toContain("draft is kept here to copy");
    expect(document.querySelector<HTMLButtonElement>(".comment-edit-save")!.disabled).toBe(true);
    click(".comment-edit-save");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

});
