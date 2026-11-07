(function() {
	//#region \0@oxc-project+runtime@0.153.0/helpers/esm/asyncToGenerator.js
	function asyncGeneratorStep(n, t, e, r, o, a, c) {
		try {
			var i = n[a](c), u = i.value;
		} catch (n) {
			e(n);
			return;
		}
		i.done ? t(u) : Promise.resolve(u).then(r, o);
	}
	function _asyncToGenerator(n) {
		return function() {
			var t = this, e = arguments;
			return new Promise(function(r, o) {
				var a = n.apply(t, e);
				function _next(n) {
					asyncGeneratorStep(a, r, o, _next, _throw, "next", n);
				}
				function _throw(n) {
					asyncGeneratorStep(a, r, o, _next, _throw, "throw", n);
				}
				_next(void 0);
			});
		};
	}
	//#endregion
	//#region src/comments/ajaxcomments.ts
	(() => {
		const COMMENT_SCROLL_TOP_OFFSET = 40;
		const PREVIEW_SCROLL_TOP_OFFSET = 20;
		const getObjectIdFromForm = (form) => {
			var _form$elements, _form$querySelector;
			const direct = form.getAttribute("data-object-id") || form.dataset.objectId;
			if (direct) return direct;
			const objectPkField = ((_form$elements = form.elements) === null || _form$elements === void 0 ? void 0 : _form$elements["object_pk"]) || ((_form$querySelector = form.querySelector) === null || _form$querySelector === void 0 ? void 0 : _form$querySelector.call(form, "input[name=\"object_pk\"]"));
			if (objectPkField === null || objectPkField === void 0 ? void 0 : objectPkField.value) return objectPkField.value;
			const match = /comment-form-(\d+)/.exec(form.id || "");
			return match ? match[1] : "";
		};
		const scrollToElement = (element, speedMs, offset = 0) => {
			if (!element) return;
			const top = element.getBoundingClientRect().top + window.scrollY - offset;
			window.scrollTo({
				top,
				behavior: speedMs ? "smooth" : "auto"
			});
		};
		const scrollToComment = (commentId) => {
			const element = document.getElementById(`c${commentId}`);
			if (!element) return;
			if (typeof window.on_scroll_to_comment === "function") {
				if (window.on_scroll_to_comment({ comment: element }) === false) return;
			}
			scrollToElement(element, 1e3, COMMENT_SCROLL_TOP_OFFSET);
		};
		const getCommentsDiv = (objectId) => document.getElementById(`comments-${objectId}`) || document.querySelector(`div.comments[data-object-id="${objectId}"]`);
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
			document.querySelectorAll("form.js-comments-form").forEach((el) => {
				var _form$parentNode;
				if (!(el instanceof HTMLFormElement)) return;
				const form = el;
				const objectId = getObjectIdFromForm(form);
				if (!objectId) return;
				if (!form.getAttribute("data-object-id")) form.setAttribute("data-object-id", objectId);
				if (document.getElementById(`comments-form-orig-position-${objectId}`)) return;
				if (form.closest(".js-comments-form-orig-position")) return;
				const wrapper = document.createElement("div");
				wrapper.className = "js-comments-form-orig-position";
				wrapper.id = `comments-form-orig-position-${objectId}`;
				(_form$parentNode = form.parentNode) === null || _form$parentNode === void 0 || _form$parentNode.insertBefore(wrapper, form);
				wrapper.appendChild(form);
			});
		};
		const fixBrokenCommentsDivIds = () => {
			document.querySelectorAll("div.comments").forEach((div) => {
				if (!(div.id === "comments-None" || div.id === "comments-")) return;
				let node = div.parentNode;
				for (let i = 0; i < 4 && node; i++) {
					var _node$querySelector;
					const form = (_node$querySelector = node.querySelector) === null || _node$querySelector === void 0 ? void 0 : _node$querySelector.call(node, ".js-comments-form");
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
		const removeThreadedPreview = (root) => {
			const previewLi = root === null || root === void 0 ? void 0 : root.querySelector("li.comment-preview");
			if (!previewLi) return false;
			const parent = previewLi.parentElement;
			if (parent && parent.children.length === 1) parent.remove();
			else previewLi.remove();
			return true;
		};
		const resetForm = (form) => {
			const objectId = getObjectIdFromForm(form);
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
				const parentComment = document.getElementById(`c${parentId}`);
				parent = parentComment ? parentComment.closest("li.comment-wrapper") : null;
			} else parent = getCommentsDiv(objectId);
			if (!parent) return null;
			if (data.use_threadedcomments) {
				let commentUl = parent.querySelector(":scope > ul.comment-list-wrapper:last-of-type");
				if (!commentUl) {
					const form = parent.querySelector("form.js-comments-form");
					commentUl = document.createElement("ul");
					commentUl.className = "comment-list-wrapper";
					if (!form) parent.appendChild(commentUl);
					else {
						let insertionNode = form;
						while (insertionNode && insertionNode.parentNode !== parent) insertionNode = insertionNode.parentElement;
						if (insertionNode) parent.insertBefore(commentUl, insertionNode);
						else parent.appendChild(commentUl);
					}
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
			if (!target || !data.html) return null;
			target.insertAdjacentHTML("beforeend", data.html);
			const commentsDiv = getCommentsDiv(data.object_id);
			if (commentsDiv) commentsDiv.classList.remove("empty");
			return data.comment_id ? document.getElementById(`c${data.comment_id}`) : null;
		};
		const removePreview = (data) => {
			var _previewArea$classLis;
			if (data.use_threadedcomments) return removeThreadedPreview(getCommentsDiv(data.object_id));
			const commentsDiv = getCommentsDiv(data.object_id);
			if (!commentsDiv) return false;
			const previewArea = commentsDiv.querySelector(".comment-preview-area");
			const hadPreview = (_previewArea$classLis = previewArea === null || previewArea === void 0 ? void 0 : previewArea.classList.contains("has-preview-loaded")) !== null && _previewArea$classLis !== void 0 ? _previewArea$classLis : false;
			if (previewArea) {
				previewArea.innerHTML = "";
				previewArea.classList.remove("has-preview-loaded");
			}
			commentsDiv.classList.remove("has-preview");
			return hadPreview;
		};
		const commentPreview = (data) => {
			const commentsDiv = getCommentsDiv(data.object_id);
			if (!commentsDiv || !data.html) return;
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
			const el = document.getElementById(id) || document.getElementById(`comment-added-message-${objectId}`);
			if (!el) return;
			el.style.display = "inline";
			setTimeout(() => {
				el.style.display = "none";
			}, 4e3);
		};
		const onCommentPosted = (data) => {
			showMessage(data.object_id, data.is_moderated === true);
			if (data.comment_id) setTimeout(() => scrollToComment(data.comment_id), 250);
		};
		const ajaxComment = function() {
			var _ref = _asyncToGenerator(function* (form, { preview }) {
				if (form.dataset.commentBusy === "1") return;
				form.dataset.commentBusy = "1";
				const ajaxUrl = form.getAttribute("data-ajax-action") || form.getAttribute("action") || "./";
				const formData = new FormData(form);
				if (preview) formData.append("preview", "1");
				const waiting = form.querySelector(".comment-waiting");
				if (waiting && !preview) waiting.style.display = "inline";
				try {
					const data = yield (yield fetch(ajaxUrl, {
						method: "POST",
						body: formData,
						credentials: "same-origin",
						headers: { "X-Requested-With": "XMLHttpRequest" }
					})).json();
					form.dataset.commentBusy = "0";
					if (waiting) waiting.style.display = "none";
					removeErrors(form);
					if (data.success) {
						if (preview) commentPreview(data);
						else {
							const current = new FormData(form);
							if (["comment", "parent"].every((field) => current.get(field) === formData.get(field))) resetForm(form);
							else if (current.get("comment") === formData.get("comment")) {
								const comment = form.elements.namedItem("comment");
								if (comment instanceof HTMLTextAreaElement) comment.value = "";
							}
							const hadPreview = removePreview(data);
							const newComment = addComment(data);
							if (hadPreview && newComment) newComment.style.display = "";
							onCommentPosted(data);
						}
					} else showErrors(form, data.errors || {});
				} catch (err) {
					form.dataset.commentBusy = "0";
					if (waiting) waiting.style.display = "none";
					if (!!window.dispatchEvent(new CustomEvent("cast:comments:error", {
						cancelable: true,
						detail: {
							error: err,
							form
						}
					}))) alert("Internal CMS error: failed to post comment data!");
					if (window.console) console.error(err);
				}
			});
			return function ajaxComment(_x, _x2) {
				return _ref.apply(this, arguments);
			};
		}();
		const onDocumentSubmit = (event) => {
			var _submitter$getAttribu;
			const form = event.target;
			if (!(form instanceof HTMLFormElement)) return;
			if (!form.matches("form.js-comments-form")) return;
			event.preventDefault();
			wrapForms();
			fixBrokenCommentsDivIds();
			const submitter = event.submitter || document.activeElement;
			const preview = ((submitter === null || submitter === void 0 || (_submitter$getAttribu = submitter.getAttribute) === null || _submitter$getAttribu === void 0 ? void 0 : _submitter$getAttribu.call(submitter, "name")) || (submitter === null || submitter === void 0 ? void 0 : submitter.name) || "") === "preview";
			ajaxComment(form, { preview });
		};
		const formForControl = (control) => {
			var _Array$from$find;
			const containing = control.closest("form.js-comments-form");
			if (containing instanceof HTMLFormElement) return containing;
			const root = control.closest(".comments");
			const objectId = (root === null || root === void 0 ? void 0 : root.getAttribute("data-object-id")) || (root === null || root === void 0 ? void 0 : root.id.replace(/^comments-/, ""));
			if (!objectId) return null;
			return (_Array$from$find = Array.from(document.querySelectorAll("form.js-comments-form")).find((form) => getObjectIdFromForm(form) === objectId)) !== null && _Array$from$find !== void 0 ? _Array$from$find : null;
		};
		const showThreadedReplyForm = (event) => {
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
			const parentField = form.querySelector("#id_parent") || form.elements["parent"];
			if (parentField) parentField.value = commentId;
		};
		const cancelThreadedReplyForm = (event) => {
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
		const getCsrfToken = () => {
			const input = document.querySelector("form.js-comments-form input[name=\"csrfmiddlewaretoken\"]");
			if (input === null || input === void 0 ? void 0 : input.value) return input.value;
			const m = /(?:^|;\s*)csrftoken=([^;]+)/.exec(document.cookie || "");
			return m ? decodeURIComponent(m[1]) : "";
		};
		const postAction = function() {
			var _ref3 = _asyncToGenerator(function* (url, fields) {
				const formData = new FormData();
				Object.entries(fields).forEach(([k, v]) => formData.append(k, v));
				formData.append("csrfmiddlewaretoken", getCsrfToken());
				const controller = new AbortController();
				let timer;
				const deadline = new Promise((_, reject) => {
					timer = setTimeout(() => {
						controller.abort();
						reject(/* @__PURE__ */ new Error("Comment action timed out."));
					}, 15e3);
				});
				const request = function() {
					var _ref2 = _asyncToGenerator(function* () {
						const response = yield fetch(url, {
							method: "POST",
							body: formData,
							signal: controller.signal,
							credentials: "same-origin",
							headers: {
								"X-Requested-With": "XMLHttpRequest",
								"X-CSRFToken": getCsrfToken()
							}
						});
						if (!response.ok) return null;
						const data = yield response.json();
						return data && typeof data === "object" && data.success === true ? data : null;
					});
					return function request() {
						return _ref2.apply(this, arguments);
					};
				}();
				try {
					return yield Promise.race([request(), deadline]);
				} finally {
					clearTimeout(timer);
				}
			});
			return function postAction(_x3, _x4) {
				return _ref3.apply(this, arguments);
			};
		}();
		const actionStatus = (root, message) => {
			let status = root.querySelector(".comment-action-status");
			if (!status) {
				status = document.createElement("p");
				status.className = "comment-action-status";
				status.setAttribute("role", "status");
				root.appendChild(status);
			}
			status.textContent = message;
		};
		const removeCommentNode = (commentId) => {
			const node = document.getElementById(`c${commentId}`);
			if (!node) return;
			(node.closest("li.comment-wrapper") || node).remove();
		};
		const onDeleteClick = function() {
			var _ref4 = _asyncToGenerator(function* (event) {
				var _event$target, _event$target$closest;
				const a = (_event$target = event.target) === null || _event$target === void 0 || (_event$target$closest = _event$target.closest) === null || _event$target$closest === void 0 ? void 0 : _event$target$closest.call(_event$target, ".comment-delete-link");
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
					const data = yield postAction(url, { comment_id: commentId });
					if (!(data === null || data === void 0 ? void 0 : data.success)) throw new Error("Delete failed.");
					if ((item === null || item === void 0 ? void 0 : item.isConnected) && document.getElementById(`c${commentId}`) === item) removeCommentNode(commentId);
				} catch (_unused) {
					if (item === null || item === void 0 ? void 0 : item.isConnected) actionStatus(item, "Could not delete this comment. Try again.");
				} finally {
					a.dataset.actionBusy = "0";
					a.removeAttribute("aria-disabled");
				}
			});
			return function onDeleteClick(_x5) {
				return _ref4.apply(this, arguments);
			};
		}();
		const openInlineEditor = (a) => {
			var _ref5, _item$querySelector$v, _item$querySelector;
			const commentId = a.getAttribute("data-comment-id");
			const url = a.getAttribute("data-edit-action");
			const item = document.getElementById(`c${commentId}`);
			if (!commentId || !url || !item) return;
			if (item.querySelector(".comment-edit-form")) return;
			const textEl = item.querySelector(".comment-text");
			const raw = (_ref5 = (_item$querySelector$v = (_item$querySelector = item.querySelector(".comment-raw")) === null || _item$querySelector === void 0 ? void 0 : _item$querySelector.value) !== null && _item$querySelector$v !== void 0 ? _item$querySelector$v : textEl === null || textEl === void 0 ? void 0 : textEl.textContent) !== null && _ref5 !== void 0 ? _ref5 : "";
			const form = document.createElement("div");
			form.className = "comment-edit-form";
			form.innerHTML = "<textarea class=\"comment-edit-textarea\"></textarea><p class=\"comment-edit-note\">Editable from this browser until someone replies or your session expires.</p><button type=\"button\" class=\"comment-edit-save\">Save</button><button type=\"button\" class=\"comment-edit-cancel\">Cancel</button><span class=\"comment-edit-status\" role=\"status\" hidden></span>";
			form.querySelector(".comment-edit-textarea").value = raw;
			if (textEl) textEl.style.display = "none";
			item.insertBefore(form, textEl ? textEl.nextSibling : null);
			form.querySelector(".comment-edit-cancel").addEventListener("click", () => {
				if (textEl) textEl.style.display = "";
				form.remove();
			});
			const save = form.querySelector(".comment-edit-save");
			const textarea = form.querySelector(".comment-edit-textarea");
			const status = form.querySelector(".comment-edit-status");
			let busy = false;
			let blocked = false;
			save.addEventListener("click", _asyncToGenerator(function* () {
				if (busy || blocked || !form.isConnected) return;
				busy = true;
				save.disabled = true;
				const value = textarea.value;
				try {
					const data = yield postAction(url, {
						comment_id: commentId,
						comment: value
					});
					if (!form.isConnected || item.querySelector(".comment-edit-form") !== form) return;
					if (!(data === null || data === void 0 ? void 0 : data.success) || typeof data.html !== "string") throw new Error("Save failed.");
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
						const freshText = fresh.querySelector(".comment-text");
						if (textEl) {
							if (freshText) textEl.replaceChildren(...Array.from(freshText.childNodes));
							else textEl.textContent = value;
						}
						const raw = item.querySelector(".comment-raw");
						if (raw) raw.value = value;
						status.hidden = false;
						status.textContent = "Saved. Your newer changes are not saved yet.";
						return;
					}
					item.replaceWith(fresh);
				} catch (_unused2) {
					if (form.isConnected) {
						status.hidden = false;
						status.textContent = "Could not save your edit. Try again.";
					}
				} finally {
					busy = false;
					save.disabled = blocked;
				}
			}));
		};
		const onEditClick = (event) => {
			var _event$target2, _event$target2$closes;
			const a = (_event$target2 = event.target) === null || _event$target2 === void 0 || (_event$target2$closes = _event$target2.closest) === null || _event$target2$closes === void 0 ? void 0 : _event$target2$closes.call(_event$target2, ".comment-edit-link");
			if (!a) return;
			event.preventDefault();
			openInlineEditor(a);
		};
		const init = () => {
			var _window$location$hash;
			wrapForms();
			fixBrokenCommentsDivIds();
			document.addEventListener("submit", onDocumentSubmit, true);
			document.body.addEventListener("click", showThreadedReplyForm);
			document.body.addEventListener("click", cancelThreadedReplyForm);
			document.body.addEventListener("click", onEditClick);
			document.body.addEventListener("click", onDeleteClick);
			if ((_window$location$hash = window.location.hash) === null || _window$location$hash === void 0 ? void 0 : _window$location$hash.startsWith("#c")) {
				const id = parseInt(window.location.hash.slice(2), 10);
				if (!Number.isNaN(id)) setTimeout(() => scrollToComment(id), 100);
			}
		};
		if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
		else init();
	})();
	//#endregion
})();
