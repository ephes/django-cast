# Editor API rendered-preview endpoint — design

Status: shaping complete (2026-06-30). Ready to split into an implementation slice.

Parent PRD:
[2026-06-19-programmatic-content-editing-api.md](2026-06-19-programmatic-content-editing-api.md)
(see the rendered-preview open question and "Why the editor API has its own read endpoints").

## Problem

The editor API lets a trusted/token client create, read, update, and publish drafts, with scoped-token enforcement
([2026-06-30-editor-api-scoped-token-auth.md](2026-06-30-editor-api-scoped-token-auth.md), shipped in 0.2.61). The
one remaining gap in the token-only/non-admin authoring loop is **preview**: the API returns an admin-session
`preview_url` (`wagtailadmin_pages:view_draft`) that only renders for a human in a Wagtail admin session. A
token-only or non-admin client cannot self-render a draft to verify it before publishing.

This slice adds a server-rendered draft preview endpoint that returns the rendered draft HTML, reusing django-cast's
existing Wagtail preview machinery, gated by the same Wagtail page permissions as the rest of the editor API.

## De-risking spike (2026-06-30)

A throwaway test confirmed the rendering path works outside `serve()`:

- `revision.as_object().make_preview_request()` returns **HTTP 200**, `Content-Type: text/html`, a full ~5 KB
  themed page.
- It renders the **draft** revision's content (draft body/title present) and **not** the live content, when called
  on `get_latest_revision_as_object()`.
- The theme template resolved correctly with no incoming `serve()` request.

`Post` already implements `serve_preview()` / `get_preview_context()` (`src/cast/models/pages.py`), including draft
media-rendition sync (`create_missing_renditions_for_posts`) and theme resolution (`get_template_base_dir`). The
endpoint therefore reuses this path rather than building rendering.

## Decisions

### Endpoints

Mirror the publish actions with one read endpoint per content type:

```
GET /api/editor/posts/{id}/preview/
GET /api/editor/episodes/{id}/preview/
```

### Response contract

- **Success: HTTP 200 `text/html; charset=utf-8`** — the full themed draft page, i.e. the body of the response
  produced by `make_preview_request()`, passed through unchanged. A client can drop it straight into an
  iframe/browser, matching what the admin preview URL serves.
- **Failure: the existing editor JSON envelope** (`application/json`) via `editor_exception_handler` —
  `not_found` (404), `permission_denied` (403), and (practically never, see below) `insufficient_scope` (403).
- This content-type split — HTML on success, JSON on error — is intentional and must be documented in the API
  reference.

### What is rendered, and which revision

- The **full themed page**, not a body fragment (it is what `make_preview_request()` returns and what the author
  ultimately publishes).
- The **latest editable revision**: `page.get_latest_revision_as_object()` (the draft if one exists, otherwise the
  live revision; Wagtail handles the no-revision fallback). This matches the object the read/update/publish
  endpoints already operate on, so a preview shows exactly what a subsequent publish would push live. Per-revision
  preview (`?revision_id=`) is out of scope; add it later only if a concrete need appears.
- Rendering call: `draft.make_preview_request(original_request=request)`, passing the incoming request so host and
  theme-selection context (cookie/query) are honored. The endpoint returns a Django `HttpResponse` carrying that
  response's content and `text/html` content type.

### Permissions and scope

- It is a `GET`, so under the scope model it is **read scope-free**: `required_scopes = {"GET": None}`.
- Authorization reuses the existing chain: authenticated user + Wagtail admin access (`HasWagtailAdminAccess`) +
  **`can_edit`** on the target page. Requiring edit permission ensures unpublished content never leaks beyond a
  caller who could already edit (and thus already preview) it. This reuses `_get_post` / `_get_episode`, which
  already enforce `can_edit` and raise the structured `not_found` / `permission_denied`.
- Because reads are scope-free, a scoped token never fails the scope check here; `insufficient_scope` is listed for
  completeness only.

### Error handling

- Missing or non-`Post` page → `404 not_found` (the episode endpoint 404s on a plain post, like the other episode
  endpoints, because `_get_episode` resolves `Episode` only).
- Caller lacks edit permission → `403 permission_denied`.
- A page with no renderable revision falls back to the live page object via `get_latest_revision_as_object()`; no
  special-casing is required (unlike publish, preview does not require an unpublished draft).
- All errors flow through the existing `editor_exception_handler`; the view does not build envelopes itself.

## Architecture

- A `PreviewMixin` (in `src/cast/api/editor/views.py`) holds the shared resolve → permission → render → respond
  logic, parameterized by the page-resolution helper. `PostPreviewView` and `EpisodePreviewView` are thin
  subclasses over `PostEditorMixin` / `EpisodeEditorMixin`, reusing `_get_post` / `_get_episode` and declaring
  `required_scopes = {"GET": None}`.
- The render helper returns a plain `django.http.HttpResponse` with the rendered content and `text/html` content
  type. It does not go through DRF content negotiation (the body is already-rendered HTML, not serializable data).

## Non-goals

- No new rendering code — reuse `make_preview_request()` / `serve_preview()`.
- No per-revision preview, no body-only fragment mode, no preview for non-editors.
- No change to the existing admin-session `preview_url` field returned by the other endpoints; it remains as-is and
  is still documented as an admin-session URL.

## First implementation slice

1. Add `PreviewMixin` with a `_render_preview(page, request)` helper returning an `HttpResponse(text/html)`.
2. Add `PostPreviewView` and `EpisodePreviewView` (thin, reusing `_get_post` / `_get_episode`, edit-permission
   denied messages, `required_scopes = {"GET": None}`).
3. Add the two URL routes in `src/cast/api/urls.py` (place `…/preview/` before the `…/{pk}/` detail route, mirroring
   the publish-route ordering).
4. Tests (`tests/api_editor_test.py`):
   - renders the latest draft (asserts a draft-only marker is present and the superseded live content is absent),
     `200 text/html`;
   - missing page → `404 not_found`; plain post on the episode endpoint → `404 not_found`;
   - caller without edit permission → `403 permission_denied`; unauthenticated → 401/403;
   - episode endpoint renders an episode draft;
   - the existing `test_every_editor_view_declares_required_scopes` guard automatically covers the new views.
5. Docs: add a "Draft preview" subsection to `docs/reference/api.rst` documenting the two endpoints, the
   `text/html` success / JSON-error split, the edit-permission requirement, and that reads need no scope; add a
   release note to `docs/releases/0.2.61.rst`.
6. Backlog: move "Editor API rendered-preview endpoint" out of Research / Shaping (implemented); update the parent
   PRD's rendered-preview open question to resolved.

## Done-when

- A caller with edit permission can `GET …/preview/` and receive the rendered latest-draft HTML for both posts and
  episodes; the superseded live content is not shown.
- Missing pages, plain posts on the episode endpoint, and callers without edit permission receive the structured
  `not_found` / `permission_denied` envelopes; no unpublished content leaks to non-editors.
- The `text/html`-success / JSON-error contract, the edit-permission requirement, and the scope-free read are
  documented; a release note is added; the backlog and parent PRD reflect the shipped endpoint.
