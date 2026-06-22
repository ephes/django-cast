# Anonymous Comment Self-Editing — Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the browser UI for anonymous comment self-editing/deletion so the already-shipped backend
(commits `e6a0ac52`, `bb1fed3e`) becomes usable: ownership-aware edit/delete controls, inline edit, an "(edited)"
marker, and the matching messaging — plus user docs and a release note.

**Architecture:** The comment UI is a single shared surface — one per-comment template
(`src/cast/comments/templates/comments/comment.html`), one TypeScript module
(`javascript/src/comments/ajaxcomments.ts` built to `src/cast/static/fluent_comments/js/ajaxcomments.js`), and one
stylesheet (`src/cast/static/fluent_comments/css/ajaxcomments.css`). All three template families (`bootstrap4`,
`plain`, `vue`) render comments through these, so the change is made once, not three times. The server tells the
template which comments the current session may act on via a small per-comment context block; the existing
event-delegation JS gains edit/delete handlers that call the backend AJAX endpoints and update the DOM in place.

**Tech Stack:** Django templates + `django_comments`/`threadedcomments`; vanilla TypeScript (no framework, no jQuery in
the comment module) built with Vite; Vitest + jsdom for JS tests; pytest for Django tests.

## Global Constraints

- Opt-in: every affordance is gated on the backend feature being active. The template must render no edit/delete control
  unless the server marks the comment editable, and `render_comment` must not assume the feature is enabled.
- No new runtime dependencies (Python or JS). CSRF via the existing comment form token; no new HTTP client.
- Match existing style: edit/delete are small text links beside the existing `reply` link; markers match the existing
  `(moderated)` flag style. Do not restyle the comment list.
- The built bundle `src/cast/static/fluent_comments/js/ajaxcomments.js` is committed; it MUST be rebuilt from the
  TypeScript source in the same commit that changes the source (the `cast.W001` check warns when source is newer).
- Identity is immutable on edit: the edit request sends only `comment_id`, `comment` text, and the CSRF token — never
  `name`/`email`/`url`.
- Endpoints already exist: `comments-edit-comment-ajax` and `comments-delete-comment-ajax`
  (`src/cast/comments/urls.py`). Edit returns `{success, comment_id (str), html, is_public, action:"edit", edited:true}`;
  delete returns `{success, action:"delete", comment_id (str)}`. Denials return 403; feature-off returns 404; rate limit
  returns 429.

---

## File Structure

- `src/cast/comments/author_edits.py` — **Modify.** Add `comment_action_context(request, comment, edited_pks=None)`
  returning the per-comment template flags. One responsibility: compute UI affordance state from session + comment.
- `src/cast/comments/templatetags/fluent_comments_tags.py` — **Modify.** `fluent_comments_list` precomputes the edited
  set once per list render and stashes it on the request; `render_comment` injects the action context per comment.
- `src/cast/comments/templates/comments/comment.html` — **Modify.** Render the `(edited)` marker, edit/delete controls,
  and a hidden raw-text source for the inline editor.
- `src/cast/comments/views.py` — **Modify.** `_rendered_comment_json` reuses `comment_action_context` so a re-rendered
  comment keeps its controls/marker.
- `javascript/src/comments/ajaxcomments.ts` — **Modify.** Add edit (inline) and delete handlers, CSRF helper, DOM
  swap/remove, and the awaiting-moderation message.
- `javascript/src/tests/ajaxcomments.test.ts` — **Modify.** Add jsdom tests for edit and delete.
- `src/cast/static/fluent_comments/js/ajaxcomments.js` — **Rebuilt artifact** (via `just js-build-comments`).
- `src/cast/static/fluent_comments/css/ajaxcomments.css` — **Modify.** Minimal styles for the controls/marker/editor.
- `tests/comment_author_edits_test.py` — **Modify.** Django tests for the context helper and template rendering.
- `docs/` user docs + `docs/releases/` release note — **Modify/Create.** Document the setting and behavior.

---

## Task 1: Server-side per-comment action context

**Files:**
- Modify: `src/cast/comments/author_edits.py`
- Test: `tests/comment_author_edits_test.py`

**Interfaces:**
- Produces: `comment_action_context(request, comment, edited_pks: set[str] | None = None) -> dict` with keys
  `can_edit: bool`, `can_delete: bool`, `edited: bool`. `can_edit`/`can_delete` are `True` only when the feature is
  enabled, the current session owns the comment, and the comment is actionable (public, not removed, not answered).
  `edited` is membership in `edited_pks` when provided (the batched path), else computed with a single query.

- [ ] **Step 1: Write the failing test**

```python
# in tests/comment_author_edits_test.py, new class
class TestActionContext:
    pytestmark = pytest.mark.django_db

    def _request(self, client, comment, owned=True):
        from django.test import RequestFactory

        rf = RequestFactory()
        request = rf.get("/")
        request.session = client.session
        if owned:
            request.session[author_edits.SESSION_KEY] = [str(comment.pk)]
        return request

    def test_owned_actionable_comment_is_editable(self, client, comment, feature_on):
        ctx = author_edits.comment_action_context(self._request(client, comment), comment)
        assert ctx["can_edit"] is True
        assert ctx["can_delete"] is True

    def test_unowned_comment_is_not_editable(self, client, comment, feature_on):
        ctx = author_edits.comment_action_context(self._request(client, comment, owned=False), comment)
        assert ctx["can_edit"] is False
        assert ctx["can_delete"] is False

    def test_disabled_feature_yields_no_controls(self, client, comment, settings):
        settings.CAST_COMMENTS_ALLOW_AUTHOR_EDITS = False
        ctx = author_edits.comment_action_context(self._request(client, comment), comment)
        assert ctx["can_edit"] is False

    def test_edited_flag_from_precomputed_set(self, client, comment, feature_on):
        ctx = author_edits.comment_action_context(
            self._request(client, comment), comment, edited_pks={str(comment.pk)}
        )
        assert ctx["edited"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/comment_author_edits_test.py::TestActionContext -q`
Expected: FAIL with `AttributeError: module 'cast.comments.author_edits' has no attribute 'comment_action_context'`

- [ ] **Step 3: Write minimal implementation**

```python
# in src/cast/comments/author_edits.py
def comment_action_context(request, comment, edited_pks=None) -> dict:
    """Per-comment UI flags for the templates: whether the current session may
    edit/delete this comment, and whether it carries an 'edited' marker."""
    session = getattr(request, "session", None)
    owns = (
        author_edits_enabled()
        and session is not None
        and owns_id(session, comment.pk)
        and comment_is_actionable(comment)
    )
    if edited_pks is not None:
        edited = str(comment.pk) in edited_pks
    else:
        edited = bool(edited_pks_for([comment.pk]))
    return {"can_edit": owns, "can_delete": owns, "edited": edited}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/comment_author_edits_test.py::TestActionContext -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/cast/comments/author_edits.py tests/comment_author_edits_test.py
git commit -m "# Add per-comment action context for author-edit UI"
```

---

## Task 2: Wire action context into comment rendering

**Files:**
- Modify: `src/cast/comments/templatetags/fluent_comments_tags.py`
- Modify: `src/cast/comments/views.py` (`_rendered_comment_json`)
- Test: `tests/comment_author_edits_test.py`

**Interfaces:**
- Consumes: `author_edits.comment_action_context` and `author_edits.edited_pks_for` from Task 1 and the backend.
- Produces: comment template context now includes `can_edit`, `can_delete`, `edited`. The request attribute
  `request._cast_edited_pks: set[str]` is set by `fluent_comments_list` and read by `render_comment` (batch path).

- [ ] **Step 1: Write the failing test**

```python
# in tests/comment_author_edits_test.py, new class
class TestRenderCommentContext:
    pytestmark = pytest.mark.django_db

    def test_render_comment_list_marks_owned_comment_editable(self, client, post, comment, comments_enabled, feature_on):
        # Own the comment in the client session, then render the post detail page.
        seed_ownership(client, comment)
        html = client.get(post.get_url()).content.decode("utf-8")
        # The edit control is rendered for the owned, actionable comment.
        assert "comment-edit-link" in html
        assert "comment-delete-link" in html

    def test_render_comment_list_no_controls_for_unowned(self, client, post, comment, comments_enabled, feature_on):
        html = client.get(post.get_url()).content.decode("utf-8")
        assert "comment-edit-link" not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/comment_author_edits_test.py::TestRenderCommentContext -q`
Expected: FAIL — `comment-edit-link` not in the rendered page (template not updated yet, and context not wired).
Note: this test also depends on Task 3's template change; it stays red until Task 3 Step 3. That is expected — this
task wires the context; Task 3 renders it. Implement both, then both go green. (If executing strictly task-by-task,
treat Task 2 + Task 3 as one review gate.)

- [ ] **Step 3: Wire the batch precompute and per-comment context**

```python
# src/cast/comments/templatetags/fluent_comments_tags.py
@register.simple_tag(takes_context=True)
def render_comment(context, comment):
    request = context.get("request")
    template_name = get_comment_template_name(comment)
    ctx = get_comment_context_data(comment)
    ctx["request"] = request
    if request is not None:
        from .. import author_edits

        edited_pks = getattr(request, "_cast_edited_pks", None)
        ctx.update(author_edits.comment_action_context(request, comment, edited_pks))
    return mark_safe(render_to_string(template_name, ctx, request=request))
```

```python
# src/cast/comments/templatetags/fluent_comments_tags.py — inside fluent_comments_list, before choosing the template
def fluent_comments_list(context):
    comment_list = context.get("comment_list")
    request = context.get("request")
    # Precompute the 'edited' set once for the whole list to avoid an N+1 query
    # in render_comment. Stored on the request; read by render_comment above.
    if request is not None:
        from .. import author_edits

        ids = [c.pk for c in comment_list] if comment_list else []
        request._cast_edited_pks = author_edits.edited_pks_for(ids)
    # ... existing target_object_id logic and render unchanged ...
```

```python
# src/cast/comments/views.py — replace the owned_comment_ids line in _rendered_comment_json
# Old: context["owned_comment_ids"] = {str(comment.pk)}
context.update(author_edits.comment_action_context(request, comment))
```

- [ ] **Step 4: Run test to verify it passes**

Run after Task 3 Step 3: `python -m pytest tests/comment_author_edits_test.py::TestRenderCommentContext -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit** (combined with Task 3 — see Task 3 Step 6)

---

## Task 3: Comment template — marker, controls, raw-text source

**Files:**
- Modify: `src/cast/comments/templates/comments/comment.html`
- Test: `tests/comment_author_edits_test.py` (the Task 2 rendering tests)

**Interfaces:**
- Consumes: template context `can_edit`, `can_delete`, `edited` from Task 2; `comment`, `USE_THREADEDCOMMENTS`,
  `request` (existing).
- Produces: DOM hooks the JS (Task 4) binds to — `.comment-edit-link`, `.comment-delete-link` (each with
  `data-comment-id` and `data-edit-action`/`data-delete-action`), `.comment-edited-flag`, and a hidden
  `.comment-raw` element holding the unrendered comment text for the inline editor.

- [ ] **Step 1: Edit the template**

Add the `(edited)` marker next to the date and the action controls in the `<h3>` block; add a hidden raw-text node
inside the comment. The controls render only when `can_edit`/`can_delete` are set, so disabled-feature pages are
unchanged.

```html
{# src/cast/comments/templates/comments/comment.html — within the comment_title block, after comment-date #}
{% if edited %}<span class="comment-edited-flag">({% trans "edited" %})</span>{% endif %}
{% if request.user.is_staff and not comment.is_public %}
  <span class="comment-moderated-flag">({% trans "moderated" %})</span>
{% endif %}
{% if USE_THREADEDCOMMENTS and not preview %}<a href="#c{{ comment.id }}" data-comment-id="{{ comment.id }}" class="comment-reply-link">{% trans "reply" %}</a>{% endif %}
{% if can_edit or can_delete %}
  <span class="comment-author-actions">
    {% if can_edit %}<a href="#c{{ comment.id }}" class="comment-edit-link" data-comment-id="{{ comment.id }}" data-edit-action="{% url 'comments-edit-comment-ajax' %}">{% trans "edit" %}</a>{% endif %}
    {% if can_delete %}<a href="#c{{ comment.id }}" class="comment-delete-link" data-comment-id="{{ comment.id }}" data-delete-action="{% url 'comments-delete-comment-ajax' %}">{% trans "delete" %}</a>{% endif %}
  </span>
{% endif %}
```

```html
{# After the comment-text div, only when editable — provides the unrendered text for the inline editor. #}
{% if can_edit %}<textarea class="comment-raw" hidden>{{ comment.comment }}</textarea>{% endif %}
```

The `comment-text` div keeps its existing `{{ comment.comment|linebreaks }}` rendering. The hidden `<textarea>` avoids
attribute-escaping pitfalls and round-trips the exact text the author submitted.

- [ ] **Step 2: Run the Task 2 rendering tests**

Run: `python -m pytest tests/comment_author_edits_test.py::TestRenderCommentContext -q`
Expected: PASS (2 passed)

- [ ] **Step 3: Add a re-render test for the edit endpoint**

```python
# in TestEditEndpoint
def test_edited_comment_html_keeps_controls_and_marker(self, client, comment, feature_on):
    from django.urls import reverse

    seed_ownership(client, comment)
    r = client.post(
        reverse("comments-edit-comment-ajax"),
        {"comment_id": str(comment.pk), "comment": "edited body"},
        **AJAX,
    )
    html = r.json()["html"]
    assert "comment-edited-flag" in html
    assert "comment-edit-link" in html
```

- [ ] **Step 4: Run it**

Run: `python -m pytest tests/comment_author_edits_test.py::TestEditEndpoint::test_edited_comment_html_keeps_controls_and_marker -q`
Expected: PASS (1 passed) — `_rendered_comment_json` now supplies `edited=True` and `can_edit=True`.

- [ ] **Step 5: Run lint/format and the full author-edits suite**

Run: `ruff check src/cast/comments/ && python -m pytest tests/comment_author_edits_test.py -q`
Expected: clean; all pass.

- [ ] **Step 6: Commit (Tasks 2 + 3 together)**

```bash
git add src/cast/comments/templatetags/fluent_comments_tags.py src/cast/comments/views.py \
  src/cast/comments/templates/comments/comment.html tests/comment_author_edits_test.py
git commit -m "# Render author edit/delete controls in the comment template"
```

---

## Task 4: TypeScript — inline edit and delete

**Files:**
- Modify: `javascript/src/comments/ajaxcomments.ts`
- Modify: `javascript/src/tests/ajaxcomments.test.ts`
- Rebuilt: `src/cast/static/fluent_comments/js/ajaxcomments.js`

**Interfaces:**
- Consumes: DOM hooks from Task 3 (`.comment-edit-link`, `.comment-delete-link`, `.comment-raw`, `#c{id}`,
  `.comment-text`) and the backend endpoints via the links' `data-edit-action`/`data-delete-action`.
- Produces: in-page edit/delete behavior. No exported API; behavior is wired in `init()` via document-level click
  delegation, consistent with the existing reply/cancel handlers.

- [ ] **Step 1: Write failing jsdom tests**

Mirror the existing test style in `javascript/src/tests/ajaxcomments.test.ts` (it imports the IIFE module to register
listeners, builds DOM, and mocks `fetch`). Add:

```ts
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
        <textarea class="comment-raw" hidden>old</textarea>
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
```

Notes for the implementer: the module self-runs on import. The existing tests re-trigger `init()` against the freshly
built DOM with `vi.resetModules(); await import("../comments/ajaxcomments");` (set up `document.body.innerHTML` first) —
the two new tests above use exactly that. Use the file's existing `flush` helper
(`const flush = () => new Promise((resolve) => setTimeout(resolve, 0))`, already defined at the top of the file).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd javascript && npm test -- ajaxcomments`
Expected: FAIL — the delete/edit handlers do not exist yet.

- [ ] **Step 3: Implement the handlers in `ajaxcomments.ts`**

Add inside the IIFE (before `init`), then register in `init()` alongside the existing click handlers.

```ts
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
  const response = await fetch(url, {
    method: "POST",
    body: formData,
    credentials: "same-origin",
    headers: { "X-Requested-With": "XMLHttpRequest", "X-CSRFToken": getCsrfToken() },
  });
  if (!response.ok) return null;
  return (await response.json()) as AjaxCommentResult;
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
  if (!window.confirm("Delete this comment?")) return;
  const data = await postAction(url, { comment_id: commentId });
  if (data?.success) removeCommentNode(commentId);
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
    `<span class="comment-edit-status" hidden></span>`;
  (form.querySelector(".comment-edit-textarea") as HTMLTextAreaElement).value = raw;
  if (textEl) textEl.style.display = "none";
  item.insertBefore(form, textEl ? textEl.nextSibling : null);

  form.querySelector(".comment-edit-cancel")!.addEventListener("click", () => {
    if (textEl) textEl.style.display = "";
    form.remove();
  });
  form.querySelector(".comment-edit-save")!.addEventListener("click", async () => {
    const value = (form.querySelector(".comment-edit-textarea") as HTMLTextAreaElement).value;
    const data = await postAction(url, { comment_id: commentId, comment: value });
    if (!data?.success || !data.html) {
      const status = form.querySelector(".comment-edit-status") as HTMLElement;
      status.hidden = false;
      status.textContent = "Could not save your edit.";
      return;
    }
    const replacement = document.createElement("div");
    replacement.innerHTML = data.html.trim();
    const fresh = replacement.firstElementChild;
    if (fresh) item.replaceWith(fresh);
    if (data.is_public === false) {
      const moderated = document.getElementById(`c${commentId}`) || fresh;
      moderated?.insertAdjacentHTML(
        "beforeend",
        `<p class="comment-edit-status">Your edit is awaiting moderation.</p>`,
      );
    }
  });
};

const onEditClick = (event: MouseEvent) => {
  const a = (event.target as Element | null)?.closest?.(".comment-edit-link");
  if (!a) return;
  event.preventDefault();
  openInlineEditor(a);
};
```

Register in `init()` next to the existing click listeners:

```ts
document.body.addEventListener("click", onEditClick);
document.body.addEventListener("click", onDeleteClick);
```

- [ ] **Step 4: Run JS tests to verify they pass**

Run: `cd javascript && npm test -- ajaxcomments`
Expected: PASS (existing + 2 new).

- [ ] **Step 5: Rebuild the committed bundle**

Run: `just js-build-comments`
Expected: regenerates `src/cast/static/fluent_comments/js/ajaxcomments.js`.

- [ ] **Step 6: Commit**

```bash
git add javascript/src/comments/ajaxcomments.ts javascript/src/tests/ajaxcomments.test.ts \
  src/cast/static/fluent_comments/js/ajaxcomments.js
git commit -m "# Add inline edit and delete handlers to comment JS"
```

---

## Task 5: Styles for controls, marker, and editor

**Files:**
- Modify: `src/cast/static/fluent_comments/css/ajaxcomments.css`

**Interfaces:**
- Consumes: the classes produced by Tasks 3–4 (`.comment-author-actions`, `.comment-edited-flag`,
  `.comment-edit-form`, `.comment-edit-note`, `.comment-edit-status`).

- [ ] **Step 1: Add minimal styles**

```css
/* Author self-edit/delete affordances */
.comment-author-actions { margin-left: 0.5em; font-size: 0.85em; }
.comment-author-actions a { margin-left: 0.5em; }
.comment-edited-flag { margin-left: 0.4em; color: #888; font-size: 0.85em; }
.comment-edit-form { margin: 0.5em 0; }
.comment-edit-form .comment-edit-textarea { width: 100%; min-height: 4em; }
.comment-edit-note { color: #888; font-size: 0.8em; margin: 0.25em 0; }
.comment-edit-status { color: #a00; font-size: 0.85em; }
```

- [ ] **Step 2: Verify the bundle/static is unaffected**

CSS is static (not built). Confirm no build step is required: `git status --short src/cast/static/fluent_comments/css/`.

- [ ] **Step 3: Commit**

```bash
git add src/cast/static/fluent_comments/css/ajaxcomments.css
git commit -m "# Style author edit/delete controls"
```

---

## Task 6: User docs and release note

**Files:**
- Modify: the comments configuration docs (locate with `git grep -l CAST_COMMENTS_ENABLED docs/`).
- Modify/Create: the current release notes file under `docs/releases/`.

**Interfaces:**
- Documents the user-facing setting and behavior; no code interface.

- [ ] **Step 1: Document the setting and behavior**

Add a section to the comments docs covering:
- `CAST_COMMENTS_ALLOW_AUTHOR_EDITS` (default `False`), opt-in.
- Requires a **server-side session backend**; the `signed_cookies` backend is rejected (`cast.E006`).
- Behavior: an author may edit or delete their own comment from the same browser until **someone replies** to it or the
  **session expires**; edits are **re-moderated** (an edit can become hidden pending moderation); deletion is a
  **soft delete**, restorable by staff in Django admin (not erasure).
- Privacy note: enabling the feature sets a **functional session cookie** for previously cookieless anonymous
  commenters.
- Optional tunables: `CAST_COMMENTS_OWNED_IDS_CAP`, `CAST_COMMENTS_EDIT_RATE_LIMIT`, `CAST_COMMENTS_EDIT_RATE_WINDOW`.

- [ ] **Step 2: Add a release note**

Add an entry to the current `docs/releases/` notes summarizing the feature (opt-in author comment self-editing/deletion)
and linking the setting docs.

- [ ] **Step 3: Update the backlog status**

In `BACKLOG.md`, update the "Anonymous comment self-editing and deletion" entry status to reflect the frontend + docs
landing. Update the PRD's Implementation Notes status line in
`backlog/2026-06-21-anonymous-comment-self-editing.md`.

- [ ] **Step 4: Commit**

```bash
git add docs/ BACKLOG.md backlog/2026-06-21-anonymous-comment-self-editing.md
git commit -m "# Document anonymous comment self-editing and add release note"
```

---

## Verification (whole feature)

- `python -m pytest tests/comment_author_edits_test.py tests/comments_test.py -q` — all pass.
- `python -m pytest -q` — full suite green.
- `cd javascript && npm test` — JS suite green.
- `ruff check src/cast/ && ruff format --check src/cast/ tests/comment_author_edits_test.py` — clean.
- `just verify-assets` (or the `cast.W001` check) — the rebuilt bundle is not stale relative to the TS source.
- Manual: with `CAST_COMMENTS_ALLOW_AUTHOR_EDITS = True` and a DB session backend, post a comment, confirm edit/delete
  controls appear only on your own comment, edit it (see `(edited)`), reply to it from a second browser, confirm the
  controls disappear (frozen), and confirm a second browser never sees controls on your comment.

## Out of Scope (deferred)

- The persistent edit-count cap and a configurable hard time-window (PRD "second slice").
- Any redesign of the comment list styling beyond the minimal control styles above.
- Vue family beyond what it already shares; it only renders comments in the styleguide today.
