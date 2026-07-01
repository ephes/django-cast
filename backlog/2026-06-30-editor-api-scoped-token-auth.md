# Editor API scoped-token / scope mapping — design

Status: implemented in 0.2.61 (2026-06-30) — `HasEditorScope` + `CAST_EDITOR_SCOPES`. This document is retained as
the design record.

Parent PRD:
[2026-06-19-programmatic-content-editing-api.md](2026-06-19-programmatic-content-editing-api.md)
(see "Authentication And Permissions" and "Open Questions").

## Problem

The editor API is deliberately authentication-mechanism agnostic: it depends only on an authenticated
`request.user` passing Wagtail page permissions, and the site chooses the DRF authentication class(es).
Scoped-token schemes (for example IndieAuth) additionally carry per-action **scopes**, so a drafting agent
can be granted a token that may create and revise drafts but may not publish — even when the underlying user
holds Wagtail publish permission.

django-cast must therefore expose a generic action→required-scope mapping and a small permission class that
enforces it from `request.auth`, **without importing any auth provider**. This document fixes the scope
vocabulary, the mapping, the permission-class behaviour (including fallbacks), naming/configurability, the
error shape, and the first implementation slice.

## Decisions

### Scope vocabulary: two logical scopes

`write` and `publish`. Reads require no scope.

Rationale: the meaningful security boundary is "can this token make content go live", not "create vs update".
Separating `publish` from `write` is the one nuance the PRD calls out — it lets a publish-capable human delegate
a draft-only token to an agent. Splitting create/update/media into distinct scopes adds surface area (more
tokens, settings, tests, docs) with no real-world protection, so it is rejected. Reads stay scope-free because
they are already gated by Wagtail edit/choose permissions and a token that can write can obviously read what it
writes.

### Action → required-scope mapping

| Action | Endpoint(s) | Required scope |
| --- | --- | --- |
| Read | `GET /api/editor/parents/`, `GET /api/editor/posts/{id}/`, `GET /api/editor/episodes/{id}/`, media list `GET` | none |
| Write | `POST /api/editor/posts/`, `POST /api/editor/episodes/`, `PATCH /api/editor/posts/{id}/`, `PATCH /api/editor/episodes/{id}/`, media upload `POST` (images/audios/videos) | `write` |
| Publish | `POST /api/editor/posts/{id}/publish/`, `POST /api/editor/episodes/{id}/publish/` | `publish` |

Scope is **necessary, not sufficient**: every action still runs its existing Wagtail permission check
(`can_add_subpage` / `can_edit` / `can_publish`) in the view body. The scope layer can only further restrict,
never widen, what Wagtail already allows.

`GET /api/editor/media/collections/` is discovery for uploads; it requires no scope (it lists where the caller
could upload and is read-only).

### How the requirement attaches: per-method `required_scopes` mapping

The required scope must be resolved **per HTTP method**, not per view, because several shipped editor views serve
both a read and a write method on the same path — for example `PostDetailView` / `EpisodeDetailView` handle `GET`
(no scope) and `PATCH` (`write`), and the media list/upload views handle `GET` (no scope) and `POST` (`write`). A
single per-view attribute could not represent that without either requiring `write` for reads or failing open for
`PATCH`.

Each editor view (or its mixin) therefore declares a class attribute mapping HTTP method to required scope:

```python
required_scopes: dict[str, str | None]  # method -> None | "write" | "publish"
```

| View | `required_scopes` |
| --- | --- |
| `ParentsListView` | `{"GET": None}` |
| `PostCreateView`, `EpisodeCreateView` | `{"POST": "write"}` |
| `PostDetailView`, `EpisodeDetailView` | `{"GET": None, "PATCH": "write"}` |
| `PostPublishView`, `EpisodePublishView` | `{"POST": "publish"}` |
| media list/upload views (images/audios/videos) | `{"GET": None, "POST": "write"}` |
| `EditorMediaCollectionsView` | `{"GET": None}` |

**Every editor view must declare an entry for every method it serves** — including reads, which declare `None`.
There is **no permissive default**: the base `EditorAPIView` sets `required_scopes = {}` (empty). The permission
class resolves `view.required_scopes.get(request.method, _REQUIRED_SCOPE_UNSET)`; an undeclared method yields the
unset sentinel. A silent `None` default would *fail open* — a future mutating method that forgot its entry would
inherit "no scope required" and bypass scope enforcement.

- The permission class treats the unset sentinel as a **fail-closed configuration error** and denies the request
  (it never silently allows a write through an undeclared method). `OPTIONS`/`HEAD` are short-circuited as allowed
  before the lookup (DRF metadata / non-mutating), so they need no entry.
- A test guard (`test_every_editor_view_declares_required_scopes`) enumerates the editor views from the URLconf
  and asserts that, for each, every implemented handler method has an explicit `required_scopes` entry whose value
  is one of `None` / `"write"` / `"publish"` — so an undeclared method fails CI rather than shipping a scope-free
  write.

### Permission class: `HasEditorScope`

Appended to `EditorAPIView.permission_classes` after `HasWagtailAdminAccess`, so the existing
authenticated-user and Wagtail-admin-access gates run first. `has_permission` logic:

1. If `request.method` is `OPTIONS`/`HEAD` → allow. Otherwise
   `required = view.required_scopes.get(request.method, _REQUIRED_SCOPE_UNSET)`. If it is the unset sentinel →
   **deny** (fail closed; an undeclared method is a configuration error caught by the test guard). If `None` →
   allow (a read).
2. `scopes = get_request_scopes(request.auth)`:
   - `request.auth is None` (Django session, no token) → return `None`.
   - token present but exposes no recognised scope attribute (unscoped, e.g. DRF `TokenAuthentication`) →
     return `None`.
   - token exposes scopes → return them as a `set[str]`.
3. If `scopes is None` → **allow** (defer to Wagtail permissions). This keeps the layer inert until a scoped
   backend is plugged in, and preserves the documented DRF `TokenAuthentication` drop-in (an unscoped token is
   full-account access).
4. Otherwise require that some configured scope string for `required` is present in `scopes`; if not, raise the
   scope error (below).

### Reading scopes from `request.auth`: `get_request_scopes`

One small, overridable function is the only place that touches token internals. It reads the OAuth/IndieAuth
convention:

- `auth.scope` — a space-separated string (OAuth/IndieAuth convention) → split on whitespace.
- `auth.scopes` — an iterable of strings.
- neither present (or `auth is None`) → return `None` (meaning "no scope information", treated as full
  authority per decision 3 above).

Returning `None` vs a set is deliberate. `None` means "this token does not carry scope information" and is
treated as full authority (allow, defer to Wagtail). A token that *does* advertise `scope`/`scopes` is "scoped":
its set is matched against the requirement, so a scoped token that lacks the required scope — including one whose
advertised set is empty — is denied write/publish (it can still read, because read methods map to `None`
and short-circuit at step 1).

### Scope-name configurability

A setting maps each logical scope to the set of token-scope strings that satisfy it:

```python
CAST_EDITOR_SCOPES = {
    "write": {"write", "create", "update"},
    "publish": {"publish"},
}
```

The default for `write` accepts the standard IndieAuth post-write scopes `create` and `update` (django-cast has a
single write bucket, so both map to it — see decision 3), letting a typical IndieAuth token create and revise
drafts out of the box. Scopes that mean something narrower in the issuer's model are intentionally **not** bundled
into `write` by default — notably IndieAuth's `media` scope, which authorises the upload endpoint rather than post
editing; bundling it would let a media-only token edit posts. A deployment that wants such a scope to grant editor
write access adds it via this setting. The check in step 4 is `bool(scopes & CAST_EDITOR_SCOPES[required])`. Sites
may override to tighten, widen, or rename, preserving the auth-agnostic boundary.

### Error shape

A scope failure returns HTTP **403** with code `insufficient_scope` (the OAuth bearer-token convention),
rendered through the existing editor error envelope as a flat `{ "code": "insufficient_scope", "detail": ... }`.
A dedicated code (rather than reusing `permission_denied`) lets a client distinguish "your token lacks the
required scope" from "Wagtail forbids this action for this user". Implemented as a new `EditorFlatError`-style
exception (or `EditorFlatError("insufficient_scope", ..., status_code=403)`) so it flows through
`editor_exception_handler` unchanged.

### Rendered-preview dependency: not a blocker

The PRD open question — "must rendered preview ship before scoped-token auth?" — is resolved **no**. This item
ships only the scope mapping/enforcement, which is inert until a site adds a scoped-token backend. A site can
adopt scoped tokens and create / read / update / publish drafts immediately; it merely lacks *self-rendered*
draft preview (the admin `preview_url` is already documented as an admin-session URL that may fail for
non-admin/token callers). Rendered preview remains an independent, parallel shaping item. This resolution is
recorded back in the parent PRD's Open Questions.

## Non-goals

- No authentication backend ships here. IndieAuth / DRF token / session remain a site's config-only choice via
  DRF `authentication_classes`; django-cast still never imports a provider.
- No new scopes beyond `write`/`publish`. A future `delete` scope can be added when a delete endpoint exists.
- No change to the existing Wagtail permission checks in view bodies; the scope layer only adds a gate.

## First implementation slice

1. Add `get_request_scopes(auth)` and the `HasEditorScope` permission class in the editor API package.
2. Add the `CAST_EDITOR_SCOPES` setting with documented defaults and resolution helper.
3. Add the `_REQUIRED_SCOPE_UNSET` sentinel and the empty base `EditorAPIView.required_scopes = {}`, and set an
   explicit per-method `required_scopes` on every concrete editor view / mixin per the mapping table.
4. Append `HasEditorScope` to `EditorAPIView.permission_classes`.
5. Add the `insufficient_scope` 403 error (envelope + handler path).
6. Tests using a fake scoped-token authentication class (no real provider dependency):
   - session auth (`request.auth is None`) → all actions allowed subject to Wagtail perms;
   - unscoped token (no `scope`/`scopes`) → allowed subject to Wagtail perms;
   - scoped token missing the required scope → 403 `insufficient_scope`, no mutation;
   - `write`-scope token → can create/update/upload but **not** publish (publish → 403 `insufficient_scope`);
   - `publish`-scope token → can publish;
   - reads need no scope;
   - `CAST_EDITOR_SCOPES` override is honoured (custom scope string satisfies `write`);
   - `test_every_editor_view_declares_required_scopes` — every editor view from the URLconf declares an explicit
     `required_scopes` entry for each method it serves, and a method left at the unset sentinel is denied (fail
     closed); a mixed-method view (`GET` + `PATCH`) allows the read without a scope but requires `write` on the
     write method.
7. Docs: extend `docs/reference/api.rst` "Authorization" section with the scope mapping, the unscoped-token and
   session fallbacks, `CAST_EDITOR_SCOPES`, and the `insufficient_scope` error; add a release note.
8. PRD: mark the scoped-token open question resolved and record the rendered-preview non-blocking decision.

## Done-when

- The action→scope mapping, the session and unscoped-token fallbacks, and `CAST_EDITOR_SCOPES` are implemented
  and documented; the auth-agnostic boundary is preserved (no provider import).
- A scoped token can be restricted to draft-only (write without publish) and that is enforced and tested.
- Docs and release notes describe the mapping, fallbacks, and `insufficient_scope` error.
