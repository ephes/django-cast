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

  const removeThreadedPreview = () => {
    const previewLi = document.querySelector("li.comment-preview");
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
  };

  const addCommentWrapper = (data: AjaxCommentResult, forPreview: boolean) => {
    const objectId = data.object_id;
    const parentId = data.parent_id;

    let parent: HTMLElement | null;
    if (parentId) {
      const parentComment = document.getElementById(`c${parseInt(parentId, 10)}`);
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
    if (data.use_threadedcomments) return removeThreadedPreview();
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
          resetForm(form);
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
    removeThreadedPreview();
    const form = document.querySelector("form.js-comments-form");
    if (!(form instanceof HTMLFormElement)) return;
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
    const form = document.querySelector("form.js-comments-form");
    if (!(form instanceof HTMLFormElement)) return;
    resetForm(form);
    removeThreadedPreview();
  };

  const init = () => {
    wrapForms();
    fixBrokenCommentsDivIds();
    document.addEventListener("submit", onDocumentSubmit, true);
    document.body.addEventListener("click", showThreadedReplyForm);
    document.body.addEventListener("click", cancelThreadedReplyForm);

    if (window.location.hash?.startsWith("#c")) {
      const id = parseInt(window.location.hash.slice(2), 10);
      if (!Number.isNaN(id)) setTimeout(() => scrollToComment(id), 100);
    }
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
