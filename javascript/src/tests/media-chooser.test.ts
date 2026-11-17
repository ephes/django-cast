import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import $ from "jquery";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const script = (type: string, suffix: string) => readFileSync(
  resolve(`../src/cast/static/cast/js/wagtail/${type}-chooser${suffix}.js`), "utf8",
);
type Request = {
  data: Record<string, string>;
  success: (data: string) => void;
  error: (response: { status: number }, status: string, error: string) => void;
  abort: ReturnType<typeof vi.fn>;
};
function markup(name: string) {
  return `<div class="modal"><div class="modal-body" data-owner="${name}">
    <form class="media-search" action="/search/${name}"><input id="id_q" value="${name}">
      <select id="collection_chooser_collection_id"><option>${name}</option><option>B</option></select></form>
    <div id="search-results"><a class="media-choice" href="/chosen/${name}">choose</a>
      <div class="pagination"><a href="?p=2" data-page="2">next</a></div></div>
    <a class="suggested-tag" href="#">tag-${name}</a>
    <section id="upload-${name}"><form class="media-upload" action="/upload/${name}">
      <li><div class="field-content"><input id="id_media-chooser-upload-title" name="media-chooser-upload-title" value="Title"></div></li>
      <input id="id_media-chooser-upload-tags" name="media-chooser-upload-tags"><input id="id_media-chooser-upload-original" name="media-chooser-upload-original" type="file"><button type="submit">Upload</button>
    </form></section></div></div>`;
}
let requests: Request[];
function mount(type: string, name: string) {
  $(document.body).append(markup(name));
  const body = $(`[data-owner="${name}"]`);
  const modal = { body, container: body.parent(), loadUrl: vi.fn(), loadResponseText: vi.fn(), close: vi.fn(), respond: vi.fn() };
  const handlers = new Function("$", "FormData", `${script(type, "-modal")}; return ${type.toUpperCase()}_CHOOSER_MODAL_ONLOAD_HANDLERS;`)($, FormData);
  handlers.chooser(modal, { error_message: "Failed", error_label: "Error" });
  return { body, modal, handlers };
}
beforeEach(() => {
  requests = [];
  document.body.innerHTML = "";
  vi.useFakeTimers();
  Object.assign($.fn, { tagit: vi.fn().mockReturnThis() });
  vi.spyOn($, "ajax").mockImplementation(((options: Request) => {
    const request = { ...options, abort: vi.fn(() => options.error?.({ status: 0 }, "abort", "abort")) };
    requests.push(request);
    return request;
  }) as unknown as typeof $.ajax);
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

describe.each(["audio", "video"])("%s chooser modal", (type) => {
  it("isolates search, page, tag, links and upload errors with duplicate IDs", () => {
    const a = mount(type, "a");
    const b = mount(type, "b");
    b.body.find(".media-search").trigger("submit");
    expect(requests[0].data).toEqual({ q: "b", collection_id: "b" });
    requests[0].success('<a class="media-choice" href="/chosen/result">result</a><div class="pagination"><a data-page="3" href="?p=3">next</a></div>');
    expect(a.body.find("#search-results").text()).toContain("choose");
    b.body.find(".pagination a").trigger("click");
    expect(requests[1].data).toEqual({ p: "3", q: "b", collection_id: "b" });
    b.body.find(".suggested-tag").trigger("click");
    expect(a.body.find("#id_q").val()).toBe("a");
    expect(requests[2].data).toEqual({ tag: "tag-b", collection_id: "b" });
    b.body.find(".media-upload").trigger("submit");
    requests[3].error({ status: 503 }, "error", "Unavailable");
    expect(b.body.find(".help-critical").text()).toContain("503");
    expect(a.body.find(".help-critical")).toHaveLength(0);
    b.body.find(".media-choice").trigger("click");
    requests[4].success("chosen");
    expect(b.modal.loadResponseText).toHaveBeenCalledExactlyOnceWith("chosen");
    expect(a.modal.loadUrl).not.toHaveBeenCalled();
  });
  it("aborts superseded results and ignores late responses", () => {
    const { body } = mount(type, "a");
    const collection = body.find("#collection_chooser_collection_id");
    collection.trigger("change");
    collection.val("B").trigger("change");
    expect(requests[0].abort).toHaveBeenCalledOnce();
    requests[1].success("new");
    requests[0].success("old");
    expect(body.find("#search-results").text()).toBe("new");
  });
  it("invalidates at input time and cancels debounce on tag/page/submit", () => {
    const { body } = mount(type, "a");
    body.find(".media-search").trigger("submit");
    body.find("#id_q").val("typed").trigger("input");
    requests[0].success("stale during debounce");
    expect(body.find("#search-results").text()).not.toContain("stale");
    body.find(".suggested-tag").trigger("click");
    vi.advanceTimersByTime(250);
    expect(requests).toHaveLength(2);
    body.find("#id_q").trigger("input");
    body.find(".pagination a").trigger("click");
    vi.advanceTimersByTime(250);
    expect(requests).toHaveLength(3);
    body.find("#id_q").trigger("input");
    body.find(".media-search").trigger("submit");
    vi.advanceTimersByTime(250);
    expect(requests).toHaveLength(4);
  });
});

describe.each(["audio", "video"])("%s chooser lifetime", (type) => {
  it.each(["close", "dialog", "chosen", "step", "reinitialize"])("retires pending timers, requests and handlers on %s", (reason) => {
    const { body, modal, handlers } = mount(type, "a");
    body.find(".media-search").trigger("submit");
    const request = requests[0];
    body.find("#id_q").trigger("input");
    if (reason === "close") modal.container.trigger("hide.bs.modal");
    if (reason === "dialog") modal.container[0].dispatchEvent(new CustomEvent("w-dialog:hide"));
    if (reason === "chosen") handlers[`${type}_chosen`](modal, { result: {} });
    if (reason === "step") handlers.select_format(modal);
    if (reason === "reinitialize") handlers.chooser(modal, {});
    request.success("retired");
    vi.advanceTimersByTime(600);
    expect(body.find("#search-results").text()).not.toContain("retired");
    expect(requests).toHaveLength(1);
    expect(request.abort).toHaveBeenCalledOnce();
    if (reason !== "reinitialize" && reason !== "step") {
      body.find("#collection_chooser_collection_id").trigger("change");
      expect(requests).toHaveLength(1);
    }
  });
  it("retires a detached modal before queued work can write", async () => {
    const { body, modal } = mount(type, "a");
    body.find(".media-upload").trigger("submit");
    body.find("#id_q").trigger("input");
    modal.container[0].remove();
    requests[0].error({ status: 503 }, "error", "late");
    requests[0].success("late response");
    await Promise.resolve();
    vi.advanceTimersByTime(600);
    expect(modal.loadResponseText).not.toHaveBeenCalled();
    expect(body.find(".help-critical")).toHaveLength(0);
    expect(requests).toHaveLength(1);
    expect(requests[0].abort).toHaveBeenCalledOnce();
  });
});

describe.each(["audio", "video"])("%s chooser upload", (type) => {
  it("admits one POST, releases on error, and advances exactly once on success", () => {
    const { body, modal } = mount(type, "a");
    const form = body.find(".media-upload");
    const button = form.find("button");
    form.trigger("submit").trigger("submit");
    expect(requests).toHaveLength(1);
    expect(button.prop("disabled")).toBe(true);
    requests[0].error({ status: 503 }, "error", "retry");
    expect(button.prop("disabled")).toBe(false);
    form.trigger("submit");
    expect(requests).toHaveLength(2);
    // A delayed callback from the failed attempt cannot settle the retry.
    requests[0].success("obsolete");
    requests[0].error({ status: 503 }, "error", "obsolete");
    expect(button.prop("disabled")).toBe(true);
    expect(modal.loadResponseText).not.toHaveBeenCalled();
    requests[1].success("chosen");
    requests[1].success("chosen twice");
    form.triggerHandler("submit");
    expect(modal.loadResponseText).toHaveBeenCalledExactlyOnceWith("chosen");
    expect(requests).toHaveLength(2);
  });
  it("discards upload callbacks and cancels its request on close", () => {
    const { body, modal } = mount(type, "a");
    body.find(".media-upload").trigger("submit");
    modal.container.trigger("hide.bs.modal");
    requests[0].success("late");
    requests[0].error({ status: 503 }, "error", "late");
    expect(requests[0].abort).toHaveBeenCalledOnce();
    expect(modal.loadResponseText).not.toHaveBeenCalled();
    expect(body.find(".help-critical")).toHaveLength(0);
  });
});

type MediaState = { id: number; title: string; edit_url: string };
type Chooser = {
  setState: (state: MediaState | null) => void;
  getState: () => MediaState | null;
  getValue: () => number | null;
  getTextLabel: () => string;
  openChooserModal: () => void;
};
function widget(type: string) {
  document.body.innerHTML = `<form id="editor"><div id="media-chooser" class="blank">
    <input id="media" type="hidden"><span class="title"></span>
    <a class="edit-link" hidden>Edit</a><button type="button" class="action-choose">Choose</button>
    <button type="button" data-chooser-action-clear>Clear</button></div></form>`;
  const workflow = vi.fn();
  Object.assign(window, { chooserUrls: { audioChooser: "/audio/", videoChooser: "/video/" } });
  const chooser: Chooser = new Function("$", "ModalWorkflow", `${type.toUpperCase()}_CHOOSER_MODAL_ONLOAD_HANDLERS = {}; ${script(type, "")}; return create${type === "audio" ? "Audio" : "Video"}Chooser('media');`)($, workflow);
  function choose(state: MediaState) {
    chooser.openChooserModal();
    workflow.mock.lastCall![0].responses[`${type}Chosen`](state);
  }
  return { chooser, choose, input: $("#media"), clear: $("[data-chooser-action-clear]") };
}
const chosen: MediaState = { id: 7, title: "Synthetic media", edit_url: "/edit/7/" };
describe.each(["audio", "video"])("%s chooser widget", (type) => {
  it("clears public, submitted and displayed state together and accepts null state", () => {
    const { chooser, choose, input, clear } = widget(type);
    choose(chosen);
    expect(chooser.getValue()).toBe(7);
    clear.trigger("click");
    expect(input.val()).toBe("");
    expect(chooser.getState()).toBeNull();
    expect(chooser.getValue()).toBeNull();
    expect(chooser.getTextLabel()).toBe("");
    expect($("#media-chooser").hasClass("blank")).toBe(true);
    expect($(".edit-link").attr("href")).toBeUndefined();
    expect($(".edit-link").attr("hidden")).toBeDefined();
    chooser.setState(chosen);
    chooser.setState(null);
    expect(input.val()).toBe("");
    expect(chooser.getState()).toBeNull();
  });
  it("bubbles one native change per user value change while hydration and repeats stay silent", () => {
    const { chooser, choose, clear } = widget(type);
    const changed = vi.fn();
    document.querySelector("#editor")!.addEventListener("change", changed);
    chooser.setState(chosen);
    chooser.setState(null);
    expect(changed).not.toHaveBeenCalled();
    choose(chosen);
    expect(changed).toHaveBeenCalledOnce();
    choose({ ...chosen });
    expect(changed).toHaveBeenCalledOnce();
    clear.trigger("click");
    expect(changed).toHaveBeenCalledTimes(2);
    clear.trigger("click");
    expect(changed).toHaveBeenCalledTimes(2);
  });
});

describe.each(["audio", "video"])("%s chooser integration boundaries", (type) => {
  it("cancels choice navigation on close and ignores its late modal step", () => {
    const { body, modal } = mount(type, "a");
    body.find(".media-choice").trigger("click");
    modal.container.trigger("hide.bs.modal");
    requests[0].success("late chosen step");
    expect(requests[0].abort).toHaveBeenCalledOnce();
    requests[0].error({ status: 503 }, "error", "late");
    expect(modal.loadResponseText).not.toHaveBeenCalled();
    expect(body.find(".help-critical")).toHaveLength(0);
  });
  it("shows a current choice request failure only in its owning modal", () => {
    const a = mount(type, "a");
    const b = mount(type, "b");
    b.body.find(".media-choice").trigger("click");
    requests[0].error({ status: 503 }, "error", "failed");
    expect(b.body.find(".help-critical").text()).toBe("Failed");
    expect(a.body.find(".help-critical")).toHaveLength(0);
  });
  it("fences a replaced body immediately, before the mutation observer runs", () => {
    const { body } = mount(type, "a");
    body.find(".media-search").trigger("submit");
    body.html('<div id="search-results">replacement step</div>');
    requests[0].success("obsolete step");
    expect(body.text()).toBe("replacement step");
    expect(requests[0].abort).toHaveBeenCalledOnce();
  });
  it("keeps missing-title validation local and admits a corrected upload", () => {
    const a = mount(type, "a");
    const b = mount(type, "b");
    b.body.find('[name="media-chooser-upload-title"]').val("");
    b.body.find(".media-upload").trigger("submit").trigger("submit");
    vi.advanceTimersByTime(600);
    expect(requests).toHaveLength(0);
    expect(b.body.find(".error-message")).toHaveLength(1);
    expect(a.body.find(".error-message")).toHaveLength(0);
    expect(b.body.find(":submit").prop("disabled")).toBe(false);
    b.body.find('[name="media-chooser-upload-title"]').val("Corrected");
    b.body.find(".media-upload").trigger("submit");
    expect(requests).toHaveLength(1);
  });
  it("populates only its own prefixed title from the changed upload file", () => {
    const a = mount(type, "a");
    const b = mount(type, "b");
    const title = b.body.find('[name="media-chooser-upload-title"]');
    title.val("");
    const file = b.body.find('input[type="file"]');
    Object.defineProperty(file[0], "value", { value: "C:\\fakepath\\synthetic.mp4", configurable: true });
    file.trigger("change");
    expect(title.val()).toBe("synthetic.mp4");
    expect(a.body.find('[name="media-chooser-upload-title"]').val()).toBe("Title");
  });
  it("hydrates a duplicated cleared state through the shipped telepath adapter silently", () => {
    const { chooser, choose, clear } = widget(type);
    choose(chosen);
    clear.trigger("click");
    const changed = vi.fn();
    document.querySelector("#editor")!.addEventListener("change", changed);
    const register = vi.fn();
    const create = new Function("$", `${script(type, "")}; return create${type === "audio" ? "Audio" : "Video"}Chooser;`)($);
    new Function("window", `create${type === "audio" ? "Audio" : "Video"}Chooser`, script(type, "-telepath"))({ telepath: { register } }, create);
    const Adapter = register.mock.lastCall![1];
    const adapter = new Adapter(`<div id="__ID__-chooser"><span class="title">stale</span><a class="edit-link" href="/stale">Edit</a></div><input id="__ID__">`, "__ID__");
    const placeholder = document.createElement("div");
    document.querySelector("#editor")!.append(placeholder);
    const duplicate = adapter.render(placeholder, "copy", "copy", chooser.getState());
    expect(duplicate.getState()).toBeNull();
    expect(duplicate.getValue()).toBeNull();
    expect(duplicate.getTextLabel()).toBe("");
    expect($("#copy").val()).toBe("");
    expect($("#copy-chooser").hasClass("blank")).toBe(true);
    expect(changed).not.toHaveBeenCalled();
  });
});
