(() => {
  const COMMENT_SCROLL_TOP_OFFSET = 40;
  const PREVIEW_SCROLL_TOP_OFFSET = 20;

  const scrollToElement = (element, speedMs, offset = 0) => {
    if (!element) return;
    const top = element.getBoundingClientRect().top + window.scrollY - offset;
    window.scrollTo({ top, behavior: speedMs ? "smooth" : "auto" });
  };

  const scrollToComment = (commentId) => {
    const element = document.getElementById(`c${commentId}`);
    if (!element) return;
    if (typeof window.on_scroll_to_comment === "function") {
      const res = window.on_scroll_to_comment({ comment: element });
      if (res === false) return;
    }
    scrollToElement(element, 1000, COMMENT_SCROLL_TOP_OFFSET);
  };

  const getCommentsDiv = (objectId) => document.getElementById(`comments-${objectId}`);

  const removeErrors = (form) => {
    form.querySelectorAll(".js-errors").forEach((node) => node.remove());
    form.querySelectorAll(".control-group.error").forEach((node) => node.classList.remove("error"));
    form.querySelectorAll(".form-group.has-error").forEach((node) => node.classList.remove("has-error"));
  };

  const showErrors = (form, errors) => {
    Object.entries(errors || {}).forEach(([fieldName, html]) => {
      if (!fieldName) return;
      const field = form.elements[fieldName];
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
    document.querySelectorAll("form.js-comments-form").forEach((form) => {
      const objectId = form.getAttribute("data-object-id");
      if (!objectId) return;
      if (form.closest(".js-comments-form-orig-position")) return;
      const wrapper = document.createElement("div");
      wrapper.className = "js-comments-form-orig-position";
      wrapper.id = `comments-form-orig-position-${objectId}`;
      form.parentNode.insertBefore(wrapper, form);
      wrapper.appendChild(form);
    });
  };

  const fixBrokenCommentsDivIds = () => {
    document.querySelectorAll("div.comments").forEach((div) => {
      if (!(div.id === "comments-None" || div.id === "comments-")) return;
      let node = div.parentNode;
      for (let i = 0; i < 4 && node; i++) {
        const form = node.querySelector(".js-comments-form");
        if (form) {
          const objectId = form.getAttribute("data-object-id");
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

  const resetForm = (form) => {
    const objectId = form.getAttribute("data-object-id");
    const commentField = form.elements["comment"];
    if (commentField) commentField.value = "";
    const parentField = form.elements["parent"];
    if (parentField) parentField.value = "";
    const orig = document.getElementById(`comments-form-orig-position-${objectId}`);
    if (orig) orig.appendChild(form);
  };

  const addCommentWrapper = (data, forPreview) => {
    const objectId = data.object_id;
    const parentId = data.parent_id;

    let parent;
    if (parentId) {
      const parentComment = document.getElementById(`c${parseInt(parentId, 10)}`);
      parent = parentComment ? parentComment.closest("li.comment-wrapper") : null;
    } else {
      parent = getCommentsDiv(objectId);
    }
    if (!parent) return null;

    if (data.use_threadedcomments) {
      let commentUl = parent.querySelector(":scope > ul.comment-list-wrapper:last-of-type");
      if (!commentUl) {
        const form = parent.querySelector(":scope > form.js-comments-form");
        commentUl = document.createElement("ul");
        commentUl.className = "comment-list-wrapper";
        if (form) parent.insertBefore(commentUl, form);
        else parent.appendChild(commentUl);
      }

      if (forPreview) {
        let previewLi = commentUl.querySelector("li.comment-preview:last-of-type");
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

  const addComment = (data) => {
    const target = addCommentWrapper(data, false);
    if (!target) return null;
    target.insertAdjacentHTML("beforeend", data.html);
    const commentsDiv = getCommentsDiv(data.object_id);
    if (commentsDiv) commentsDiv.classList.remove("empty");
    return document.getElementById(`c${data.comment_id}`);
  };

  const removePreview = (data) => {
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

  const commentPreview = (data) => {
    const commentsDiv = getCommentsDiv(data.object_id);
    if (!commentsDiv) return;

    if (data.use_threadedcomments) {
      const target = addCommentWrapper(data, true);
      if (!target) return;
      target.innerHTML = `<div class="comment-preview">${data.html}</div>`;
      setTimeout(() => scrollToElement(target, 500, PREVIEW_SCROLL_TOP_OFFSET), 200);
      return;
    }

    let previewArea = commentsDiv.querySelector(".comment-preview-area");
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

  const showMessage = (objectId, isModerated) => {
    const id = isModerated ? `comment-moderated-message-${objectId}` : `comment-added-message-${objectId}`;
    const el = document.getElementById(id);
    if (!el) return;
    el.style.display = "inline";
    setTimeout(() => {
      el.style.display = "none";
    }, 4000);
  };

  const onCommentPosted = (data) => {
    showMessage(data.object_id, data.is_moderated);
    setTimeout(() => scrollToComment(data.comment_id), 250);
  };

  const ajaxComment = async (form, { preview }) => {
    if (form.dataset.commentBusy === "1") return;
    form.dataset.commentBusy = "1";

    const ajaxUrl = form.getAttribute("data-ajax-action") || form.getAttribute("action") || "./";
    const formData = new FormData(form);
    if (preview) formData.append("preview", "1");

    const waiting = form.querySelector(".comment-waiting");
    if (waiting && !preview) waiting.style.display = "inline";

    try {
      const response = await fetch(ajaxUrl, {
        method: "POST",
        body: formData,
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      const data = await response.json();

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
          if (hadPreview && newComment) newComment.style.display = "";
          onCommentPosted(data);
        }
      } else {
        showErrors(form, data.errors);
      }
    } catch (err) {
      form.dataset.commentBusy = "0";
      if (waiting) waiting.style.display = "none";
      const handled = !window.dispatchEvent(
        new CustomEvent("cast:comments:error", {
          cancelable: true,
          detail: { error: err, form },
        }),
      );
      if (!handled) alert("Internal CMS error: failed to post comment data!");
      // eslint-disable-next-line no-console
      if (window.console) console.error(err);
    }
  };

  const onDocumentSubmit = (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (!form.matches("form.js-comments-form")) return;

    event.preventDefault();

    // When pages are navigated via HTMX (or any other DOM swap), the form may be
    // inserted after this script initialized. Ensure wrappers/IDs exist at the
    // point of interaction too.
    wrapForms();
    fixBrokenCommentsDivIds();

    const submitter = event.submitter || document.activeElement;
    const submitterName = submitter?.getAttribute?.("name") || submitter?.name || "";
    const preview = submitterName === "preview";

    ajaxComment(form, { preview });
  };

  const showThreadedReplyForm = (event) => {
    const a = event.target.closest(".comment-reply-link");
    if (!a) return;
    event.preventDefault();
    wrapForms();
    const commentId = a.getAttribute("data-comment-id");
    const commentWrapper = a.closest("li.comment-wrapper");
    if (!commentWrapper) return;
    removeThreadedPreview();
    const form = document.querySelector("form.js-comments-form");
    if (!form) return;
    commentWrapper.appendChild(form);
    const parentField = form.querySelector("#id_parent") || form.elements["parent"];
    if (parentField) parentField.value = commentId;
  };

  const cancelThreadedReplyForm = (event) => {
    const a = event.target.closest(".comment-cancel-reply-link");
    if (!a) return;
    event.preventDefault();
    wrapForms();
    const form = document.querySelector("form.js-comments-form");
    if (!form) return;
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
