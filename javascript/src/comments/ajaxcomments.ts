(() => {
  const COMMENT_SCROLL_TOP_OFFSET = 40;
  const PREVIEW_SCROLL_TOP_OFFSET = 20;

  const getObjectIdFromForm = (form: HTMLFormElement): string => {
    const direct = form.getAttribute("data-object-id") || form.dataset.objectId;
    if (direct) return direct;

    const objectPkField =
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (form.elements as any)?.["object_pk"] || form.querySelector?.('input[name="object_pk"]');
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    if ((objectPkField as any)?.value) return (objectPkField as any).value;

    const match = /comment-form-(\d+)/.exec(form.id || "");
    return match ? match[1] : "";
  };

  const scrollToElement = (element: HTMLElement | null, speedMs: number, offset = 0) => {
    if (!element) return;
    const top = element.getBoundingClientRect().top + window.scrollY - offset;
    window.scrollTo({ top, behavior: speedMs ? "smooth" : "auto" });
  };

  const scrollToComment = (commentId: string | number) => {
    const element = document.getElementById(`c${commentId}`);
    if (!element) return;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    if (typeof (window as any).on_scroll_to_comment === "function") {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const res = (window as any).on_scroll_to_comment({ comment: element });
      if (res === false) return;
    }
    scrollToElement(element, 1000, COMMENT_SCROLL_TOP_OFFSET);
  };

  const getCommentsDiv = (objectId: string) =>
    document.getElementById(`comments-${objectId}`) || document.querySelector(`div.comments[data-object-id="${objectId}"]`);

  const removeErrors = (form: HTMLFormElement) => {
    form.querySelectorAll(".js-errors").forEach((node) => node.remove());
    form.querySelectorAll(".control-group.error").forEach((node) => node.classList.remove("error"));
    form.querySelectorAll(".form-group.has-error").forEach((node) => node.classList.remove("has-error"));
  };

  const showErrors = (form: HTMLFormElement, errors: Record<string, string>) => {
    Object.entries(errors || {}).forEach(([fieldName, html]) => {
      if (!fieldName) return;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const field = (form.elements as any)[fieldName] as HTMLElement | undefined;
      if (!field) return;
      const error = document.createElement("span");
      error.className = "js-errors";
      error.innerHTML = html;
      field.insertAdjacentElement("afterend", error);
      const group = field.closest(".control-group") || field.closest(".form-group");
      if (group) group.classList.add(group.classList.contains("control-group") ? "error" : "has-error");
    });
  };

  const wrapForms = () => {
    document.querySelectorAll("form.js-comments-form").forEach((el) => {
      if (!(el instanceof HTMLFormElement)) return;
      const form = el;
      const objectId = getObjectIdFromForm(form);
      if (!objectId) return;
      if (!form.getAttribute("data-object-id")) form.setAttribute("data-object-id", objectId);
      const existingWrapper = document.getElementById(`comments-form-orig-position-${objectId}`);
      if (existingWrapper) return;
      if (form.closest(".js-comments-form-orig-position")) return;
      const wrapper = document.createElement("div");
      wrapper.className = "js-comments-form-orig-position";
      wrapper.id = `comments-form-orig-position-${objectId}`;
      form.parentNode?.insertBefore(wrapper, form);
      wrapper.appendChild(form);
    });
  };

  const fixBrokenCommentsDivIds = () => {
    document.querySelectorAll("div.comments").forEach((div) => {
      if (!(div.id === "comments-None" || div.id === "comments-")) return;
      let node: ParentNode | null = div.parentNode;
      for (let i = 0; i < 4 && node; i++) {
        const form = (node as HTMLElement).querySelector?.(".js-comments-form");
        if (form instanceof HTMLFormElement) {
          const objectId = getObjectIdFromForm(form);
          if (objectId) {
            div.id = `comments-${objectId}`;
            div.setAttribute("data-object-id", objectId);
          }
          break;
        }
        node = node.parentNode;
      }
    });
  };

  const removeThreadedPreview = (root: ParentNode | null) => {
    const previewLi = root?.querySelector("li.comment-preview");
    if (!previewLi) return false;
    const parent = previewLi.parentElement;
    if (parent && parent.children.length === 1) parent.remove();
    else previewLi.remove();
    return true;
  };

  const resetForm = (form: HTMLFormElement) => {
    const objectId = getObjectIdFromForm(form);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const commentField = (form.elements as any)["comment"] as HTMLTextAreaElement | undefined;
    if (commentField) commentField.value = "";
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const parentField = (form.elements as any)["parent"] as HTMLInputElement | undefined;
    if (parentField) parentField.value = "";
    const orig = document.getElementById(`comments-form-orig-position-${objectId}`);
    if (orig) orig.appendChild(form);
  };

  type AjaxCommentResult = {
    success: boolean;
    html?: string;
    errors?: Record<string, string>;
    object_id: string;
    parent_id?: string | null;
    comment_id?: string;
    use_threadedcomments: boolean;
    is_moderated?: boolean;
    is_public?: boolean;
    action?: string;
    edited?: boolean;
  };

  const addCommentWrapper = (data: AjaxCommentResult, forPreview: boolean) => {
    const objectId = data.object_id;
    const parentId = data.parent_id;

    let parent: HTMLElement | null;
    if (parentId) {
      // parent_id is sent as a string so non-integer comment PKs (e.g. UUIDs)
      // resolve; look the element up directly rather than parsing an int.
      const parentComment = document.getElementById(`c${parentId}`);
      parent = parentComment ? (parentComment.closest("li.comment-wrapper") as HTMLElement | null) : null;
    } else {
      parent = getCommentsDiv(objectId) as HTMLElement | null;
    }
    if (!parent) return null;

    if (data.use_threadedcomments) {
      let commentUl = parent.querySelector(":scope > ul.comment-list-wrapper:last-of-type") as HTMLUListElement | null;
      if (!commentUl) {
        const form = parent.querySelector("form.js-comments-form") as HTMLFormElement | null;
        commentUl = document.createElement("ul");
        commentUl.className = "comment-list-wrapper";
        if (!form) {
          parent.appendChild(commentUl);
        } else {
          let insertionNode: HTMLElement | null = form;
          while (insertionNode && insertionNode.parentNode !== parent) insertionNode = insertionNode.parentElement;
          if (insertionNode) parent.insertBefore(commentUl, insertionNode);
          else parent.appendChild(commentUl);
        }
      }

      if (forPreview) {
        let previewLi = commentUl.querySelector("li.comment-preview:last-of-type") as HTMLLIElement | null;
        if (!previewLi) {
          previewLi = document.createElement("li");
          previewLi.className = "comment-wrapper comment-preview";
          commentUl.appendChild(previewLi);
        }
        return previewLi;
      }

      const li = document.createElement("li");
      li.className = "comment-wrapper";
      commentUl.appendChild(li);
      return li;
    }

    return parent;
  };

  const addComment = (data: AjaxCommentResult) => {
    const target = addCommentWrapper(data, false);
    if (!target || !data.html) return null;
    target.insertAdjacentHTML("beforeend", data.html);
    const commentsDiv = getCommentsDiv(data.object_id);
    if (commentsDiv) commentsDiv.classList.remove("empty");
    return data.comment_id ? document.getElementById(`c${data.comment_id}`) : null;
  };

  const removePreview = (data: AjaxCommentResult) => {
    if (data.use_threadedcomments) return removeThreadedPreview(getCommentsDiv(data.object_id));
    const commentsDiv = getCommentsDiv(data.object_id);
    if (!commentsDiv) return false;
    const previewArea = commentsDiv.querySelector(".comment-preview-area");
    const hadPreview = previewArea?.classList.contains("has-preview-loaded") ?? false;
    if (previewArea) {
      previewArea.innerHTML = "";
      previewArea.classList.remove("has-preview-loaded");
    }
    commentsDiv.classList.remove("has-preview");
    return hadPreview;
  };

  const commentPreview = (data: AjaxCommentResult) => {
    const commentsDiv = getCommentsDiv(data.object_id);
    if (!commentsDiv || !data.html) return;

    if (data.use_threadedcomments) {
      const target = addCommentWrapper(data, true);
      if (!target) return;
      target.innerHTML = `<div class="comment-preview">${data.html}</div>`;
      setTimeout(() => scrollToElement(target, 500, PREVIEW_SCROLL_TOP_OFFSET), 200);
      return;
    }

    let previewArea = commentsDiv.querySelector(".comment-preview-area") as HTMLDivElement | null;
    if (!previewArea) {
      previewArea = document.createElement("div");
      previewArea.className = "comment-preview-area";
      commentsDiv.appendChild(previewArea);
      commentsDiv.classList.add("has-preview");
    }
    previewArea.innerHTML = `<div class="comment-preview">${data.html}</div>`;
    previewArea.classList.add("has-preview-loaded");
    setTimeout(() => scrollToElement(previewArea, 500, PREVIEW_SCROLL_TOP_OFFSET), 200);
  };

  const showMessage = (objectId: string, isModerated: boolean) => {
    const id = isModerated ? `comment-moderated-message-${objectId}` : `comment-added-message-${objectId}`;
    const el = document.getElementById(id) || document.getElementById(`comment-added-message-${objectId}`);
    if (!el) return;
    el.style.display = "inline";
    setTimeout(() => {
      el.style.display = "none";
    }, 4000);
  };

  const onCommentPosted = (data: AjaxCommentResult) => {
    showMessage(data.object_id, data.is_moderated === true);
    if (data.comment_id) setTimeout(() => scrollToComment(data.comment_id!), 250);
  };

  const ajaxComment = async (form: HTMLFormElement, { preview }: { preview: boolean }) => {
    if (form.dataset.commentBusy === "1") return;
    form.dataset.commentBusy = "1";

    const ajaxUrl = form.getAttribute("data-ajax-action") || form.getAttribute("action") || "./";
    const formData = new FormData(form);
    if (preview) formData.append("preview", "1");

    const waiting = form.querySelector(".comment-waiting") as HTMLElement | null;
    if (waiting && !preview) waiting.style.display = "inline";

    try {
      const response = await fetch(ajaxUrl, {
        method: "POST",
        body: formData,
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      const data = (await response.json()) as AjaxCommentResult;

      form.dataset.commentBusy = "0";
      if (waiting) waiting.style.display = "none";
      removeErrors(form);

      if (data.success) {
        if (preview) {
          commentPreview(data);
        } else {
          const current = new FormData(form);
          if (["comment", "parent"].every((field) => current.get(field) === formData.get(field))) {
            resetForm(form);
          } else if (current.get("comment") === formData.get("comment")) {
            const comment = form.elements.namedItem("comment");
            if (comment instanceof HTMLTextAreaElement) comment.value = "";
          }
          const hadPreview = removePreview(data);
          const newComment = addComment(data);
          if (hadPreview && newComment) (newComment as HTMLElement).style.display = "";
          onCommentPosted(data);
        }
      } else {
        showErrors(form, data.errors || {});
      }
    } catch (err) {
      form.dataset.commentBusy = "0";
      if (waiting) waiting.style.display = "none";
      const handled = !window.dispatchEvent(
        new CustomEvent("cast:comments:error", {
          cancelable: true,
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          detail: { error: err as any, form },
        }),
      );
      if (!handled) alert("Internal CMS error: failed to post comment data!");
      // eslint-disable-next-line no-console
      if (window.console) console.error(err);
    }
  };

  const onDocumentSubmit = (event: SubmitEvent) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (!form.matches("form.js-comments-form")) return;

    event.preventDefault();

    // When pages are navigated via HTMX (or any other DOM swap), the form may be
    // inserted after this script initialized. Ensure wrappers/IDs exist at the
    // point of interaction too.
    wrapForms();
    fixBrokenCommentsDivIds();

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const submitter = (event as any).submitter || document.activeElement;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const submitterName = (submitter as any)?.getAttribute?.("name") || (submitter as any)?.name || "";
    const preview = submitterName === "preview";

    ajaxComment(form, { preview });
  };

  const formForControl = (control: Element): HTMLFormElement | null => {
    const containing = control.closest("form.js-comments-form");
    if (containing instanceof HTMLFormElement) return containing;
    const root = control.closest(".comments");
    const objectId = root?.getAttribute("data-object-id") || root?.id.replace(/^comments-/, "");
    if (!objectId) return null;
    return Array.from(document.querySelectorAll<HTMLFormElement>("form.js-comments-form"))
      .find((form) => getObjectIdFromForm(form) === objectId) ?? null;
  };

  const showThreadedReplyForm = (event: MouseEvent) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const a = target.closest(".comment-reply-link");
    if (!a) return;
    event.preventDefault();
    wrapForms();
    const commentId = a.getAttribute("data-comment-id");
    const commentWrapper = a.closest("li.comment-wrapper");
    if (!commentWrapper || !commentId) return;
    const form = formForControl(a);
    if (!form) return;
    removeThreadedPreview(a.closest(".comments"));
    commentWrapper.appendChild(form);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const parentField = (form.querySelector("#id_parent") as HTMLInputElement | null) || (form.elements as any)["parent"];
    if (parentField) parentField.value = commentId;
  };

  const cancelThreadedReplyForm = (event: MouseEvent) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const a = target.closest(".comment-cancel-reply-link");
    if (!a) return;
    event.preventDefault();
    wrapForms();
    const form = formForControl(a);
    if (!form) return;
    const root = form.closest(".comments") || getCommentsDiv(getObjectIdFromForm(form));
    resetForm(form);
    removeThreadedPreview(root);
  };

  const getCsrfToken = (): string => {
    const input = document.querySelector<HTMLInputElement>(
      'form.js-comments-form input[name="csrfmiddlewaretoken"]',
    );
    if (input?.value) return input.value;
    const m = /(?:^|;\s*)csrftoken=([^;]+)/.exec(document.cookie || "");
    return m ? decodeURIComponent(m[1]) : "";
  };

  const postAction = async (url: string, fields: Record<string, string>): Promise<AjaxCommentResult | null> => {
    const formData = new FormData();
    Object.entries(fields).forEach(([k, v]) => formData.append(k, v));
    formData.append("csrfmiddlewaretoken", getCsrfToken());
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const deadline = new Promise<never>((_, reject) => {
      timer = setTimeout(() => {
        controller.abort();
        reject(new Error("Comment action timed out."));
      }, 15000);
    });
    const request = async () => {
      const response = await fetch(url, {
        method: "POST", body: formData, signal: controller.signal,
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest", "X-CSRFToken": getCsrfToken() },
      });
      if (!response.ok) return null;
      const data = await response.json();
      return data && typeof data === "object" && data.success === true ? data as AjaxCommentResult : null;
    };
    try {
      return await Promise.race([request(), deadline]);
    } finally {
      clearTimeout(timer);
    }
  };

  const actionStatus = (root: Element, message: string) => {
    let status = root.querySelector<HTMLElement>(".comment-action-status");
    if (!status) {
      status = document.createElement("p");
      status.className = "comment-action-status";
      status.setAttribute("role", "status");
      root.appendChild(status);
    }
    status.textContent = message;
  };

  const removeCommentNode = (commentId: string) => {
    const node = document.getElementById(`c${commentId}`);
    if (!node) return;
    const wrapper = node.closest("li.comment-wrapper");
    (wrapper || node).remove();
  };

  const onDeleteClick = async (event: MouseEvent) => {
    const a = (event.target as Element | null)?.closest?.(".comment-delete-link");
    if (!a) return;
    event.preventDefault();
    const commentId = a.getAttribute("data-comment-id");
    const url = a.getAttribute("data-delete-action");
    if (!commentId || !url) return;
    if (!(a instanceof HTMLElement) || a.dataset.actionBusy === "1") return;
    if (!window.confirm("Delete this comment?")) return;
    a.dataset.actionBusy = "1";
    a.setAttribute("aria-disabled", "true");
    const item = document.getElementById(`c${commentId}`);
    try {
      const data = await postAction(url, { comment_id: commentId });
      if (!data?.success) throw new Error("Delete failed.");
      if (item?.isConnected && document.getElementById(`c${commentId}`) === item) removeCommentNode(commentId);
    } catch {
      if (item?.isConnected) actionStatus(item, "Could not delete this comment. Try again.");
    } finally {
      a.dataset.actionBusy = "0";
      a.removeAttribute("aria-disabled");
    }
  };

  const openInlineEditor = (a: Element) => {
    const commentId = a.getAttribute("data-comment-id");
    const url = a.getAttribute("data-edit-action");
    const item = document.getElementById(`c${commentId}`);
    if (!commentId || !url || !item) return;
    if (item.querySelector(".comment-edit-form")) return; // already open
    const textEl = item.querySelector(".comment-text") as HTMLElement | null;
    const raw = (item.querySelector(".comment-raw") as HTMLTextAreaElement | null)?.value ?? (textEl?.textContent ?? "");
    const form = document.createElement("div");
    form.className = "comment-edit-form";
    form.innerHTML =
      `<textarea class="comment-edit-textarea"></textarea>` +
      `<p class="comment-edit-note">Editable from this browser until someone replies or your session expires.</p>` +
      `<button type="button" class="comment-edit-save">Save</button>` +
      `<button type="button" class="comment-edit-cancel">Cancel</button>` +
      `<span class="comment-edit-status" role="status" hidden></span>`;
    (form.querySelector(".comment-edit-textarea") as HTMLTextAreaElement).value = raw;
    if (textEl) textEl.style.display = "none";
    item.insertBefore(form, textEl ? textEl.nextSibling : null);

    form.querySelector(".comment-edit-cancel")!.addEventListener("click", () => {
      if (textEl) textEl.style.display = "";
      form.remove();
    });
    const save = form.querySelector<HTMLButtonElement>(".comment-edit-save")!;
    const textarea = form.querySelector<HTMLTextAreaElement>(".comment-edit-textarea")!;
    const status = form.querySelector<HTMLElement>(".comment-edit-status")!;
    let busy = false;
    let blocked = false;
    save.addEventListener("click", async () => {
      if (busy || blocked || !form.isConnected) return;
      busy = true;
      save.disabled = true;
      const value = textarea.value;
      try {
        const data = await postAction(url, { comment_id: commentId, comment: value });
        if (!form.isConnected || item.querySelector(".comment-edit-form") !== form) return;
        if (!data?.success || typeof data.html !== "string") throw new Error("Save failed.");
        const replacement = document.createElement("div");
        replacement.innerHTML = data.html.trim();
        const fresh = replacement.firstElementChild;
        if (!fresh) throw new Error("Save failed.");
        if (data.is_public === false) {
          actionStatus(fresh, "Your edit is awaiting moderation.");
          if (textarea.value !== value) {
            blocked = true;
            status.hidden = false;
            status.textContent = "Your newer draft is kept here to copy. Further saves are unavailable while moderation is pending.";
            fresh.appendChild(form);
          }
          item.replaceWith(fresh);
          return;
        }
        if (textarea.value !== value) {
          // Keep the editor and its newer draft. Cancel reveals the acknowledged value.
          const freshText = fresh.querySelector(".comment-text");
          if (textEl) {
            if (freshText) textEl.replaceChildren(...Array.from(freshText.childNodes));
            else textEl.textContent = value;
          }
          const raw = item.querySelector<HTMLTextAreaElement>(".comment-raw");
          if (raw) raw.value = value;
          status.hidden = false;
          status.textContent = "Saved. Your newer changes are not saved yet.";
          return;
        }
        item.replaceWith(fresh);
      } catch {
        if (form.isConnected) {
          status.hidden = false;
          status.textContent = "Could not save your edit. Try again.";
        }
      } finally {
        busy = false;
        save.disabled = blocked;
      }
    });
  };

  const onEditClick = (event: MouseEvent) => {
    const a = (event.target as Element | null)?.closest?.(".comment-edit-link");
    if (!a) return;
    event.preventDefault();
    openInlineEditor(a);
  };

  const init = () => {
    wrapForms();
    fixBrokenCommentsDivIds();
    document.addEventListener("submit", onDocumentSubmit, true);
    document.body.addEventListener("click", showThreadedReplyForm);
    document.body.addEventListener("click", cancelThreadedReplyForm);
    document.body.addEventListener("click", onEditClick);
    document.body.addEventListener("click", onDeleteClick);

    if (window.location.hash?.startsWith("#c")) {
      const id = parseInt(window.location.hash.slice(2), 10);
      if (!Number.isNaN(id)) setTimeout(() => scrollToComment(id), 100);
    }
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();

export {};
