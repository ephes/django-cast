import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("ajaxcomments", () => {
  beforeEach(() => {
    // JSDOM doesn't implement scrollTo; the script calls it via setTimeout.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (window as any).scrollTo = vi.fn();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (globalThis as any).fetch = undefined;
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
});
