# Editor API Scoped-Token Scope Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce a generic, auth-provider-agnostic per-action scope check (`write`/`publish`) on the editor API so a scoped-token backend can restrict a token to draft-only, while session and unscoped tokens fall back to pure Wagtail permissions.

**Architecture:** A new `src/cast/api/editor/scopes.py` holds a sentinel, a `get_request_scopes(auth)` reader, and a `HasEditorScope` DRF permission class. Each editor view declares a per-method `required_scopes` mapping; the base `EditorAPIView` declares an empty mapping and appends `HasEditorScope` to its `permission_classes`. Scope failures raise the existing `EditorFlatError` with code `insufficient_scope` (HTTP 403). The scope→accepted-strings mapping is the configurable `CAST_EDITOR_SCOPES` setting.

**Tech Stack:** Django, Django REST Framework, Wagtail, pytest.

## Global Constraints

- django-cast must not import any authentication provider (IndieAuth/OAuth/etc.); the scope layer reads only `request.auth` duck-typed attributes. (verbatim intent from spec "Non-goals")
- Scope is **necessary, not sufficient**: existing Wagtail permission checks in view bodies remain unchanged and are the final authority.
- Fallbacks: `request.auth is None` (session) and a token exposing no scope info (unscoped) both → allow at the scope layer (defer to Wagtail).
- No permissive default: a served method with no explicit `required_scopes` entry must fail closed (deny), and a test guard must catch undeclared methods in CI.
- Only two logical scopes ship: `write` and `publish`. No `delete`/`create`/`update` split.
- Reads (`GET`) require no scope; `OPTIONS`/`HEAD` are always allowed.
- Settings follow the `src/cast/appsettings.py` `_DYNAMIC_SETTING_DEFAULTS` + `__getattr__` pattern; read settings via `from cast import appsettings` then `appsettings.CAST_EDITOR_SCOPES` so `@override_settings` works.
- Source spec: `backlog/2026-06-30-editor-api-scoped-token-auth.md`.

---

### Task 1: Scope reader and configurable scope mapping

**Files:**
- Create: `src/cast/api/editor/scopes.py`
- Modify: `src/cast/appsettings.py` (add `CAST_EDITOR_SCOPES` to `_DYNAMIC_SETTING_DEFAULTS` and the `TYPE_CHECKING` block)
- Test: `tests/api_editor_test.py` (new `TestEditorScopeReader` class)

**Interfaces:**
- Produces:
  - `cast.api.editor.scopes._REQUIRED_SCOPE_UNSET: object` — module-level sentinel.
  - `cast.api.editor.scopes.get_request_scopes(auth: Any) -> set[str] | None` — returns the token's scope set, or `None` when `auth` is `None` or exposes no `scope`/`scopes` attribute.
  - `appsettings.CAST_EDITOR_SCOPES: dict[str, set[str]]` — logical-scope → accepted token-scope strings.

- [ ] **Step 1: Write the failing test**

Add to `tests/api_editor_test.py` (near the other unit-style classes; it needs no DB):

```python
class TestEditorScopeReader:
    def test_none_auth_returns_none(self):
        from cast.api.editor.scopes import get_request_scopes

        assert get_request_scopes(None) is None

    def test_space_separated_scope_string_is_split(self):
        from cast.api.editor.scopes import get_request_scopes

        token = type("Tok", (), {"scope": "write publish"})()
        assert get_request_scopes(token) == {"write", "publish"}

    def test_scopes_iterable_is_collected(self):
        from cast.api.editor.scopes import get_request_scopes

        token = type("Tok", (), {"scopes": ["write"]})()
        assert get_request_scopes(token) == {"write"}

    def test_token_without_scope_info_returns_none(self):
        from cast.api.editor.scopes import get_request_scopes

        token = type("Tok", (), {})()
        assert get_request_scopes(token) is None

    def test_empty_scope_string_is_empty_set_not_none(self):
        from cast.api.editor.scopes import get_request_scopes

        token = type("Tok", (), {"scope": ""})()
        assert get_request_scopes(token) == set()

    def test_non_string_scope_value_fails_closed(self):
        # ``scope`` is string-only by convention; a list must NOT be coerced into granted
        # scopes (that would fail open). It fails closed to an empty set.
        from cast.api.editor.scopes import get_request_scopes

        token = type("Tok", (), {"scope": ["write"]})()
        assert get_request_scopes(token) == set()

    def test_empty_scopes_iterable_is_empty_set(self):
        from cast.api.editor.scopes import get_request_scopes

        token = type("Tok", (), {"scopes": []})()
        assert get_request_scopes(token) == set()

    def test_scopes_accepts_any_non_string_iterable(self):
        # The contract is "iterable of scope strings", not "list" — a generator works.
        from cast.api.editor.scopes import get_request_scopes

        token = type("Tok", (), {"scopes": iter(["write", "publish"])})()
        assert get_request_scopes(token) == {"write", "publish"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api_editor_test.py::TestEditorScopeReader -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cast.api.editor.scopes'`.

- [ ] **Step 3: Create the scopes module**

Create `src/cast/api/editor/scopes.py`:

```python
from __future__ import annotations

from typing import Any

_REQUIRED_SCOPE_UNSET = object()


def get_request_scopes(auth: Any) -> set[str] | None:
    """Read OAuth/IndieAuth-style scopes off ``request.auth``.

    Returns ``None`` only when there is no scope information at all (``auth is None`` or a
    token whose ``scope``/``scopes`` attributes are both absent or ``None``), which callers
    treat as "unscoped → full authority, defer to Wagtail". A token that *advertises*
    scope info — even malformed or empty (``""``, ``[]``) — returns a (possibly empty) set
    that is matched against the requirement, so a present-but-empty scope fails closed
    rather than falling open to ``None``.
    """
    if auth is None:
        return None
    scope = getattr(auth, "scope", None)
    if isinstance(scope, str):
        # OAuth/IndieAuth convention: ``scope`` is a space-separated string ("" -> set()).
        return set(scope.split())
    scopes = getattr(auth, "scopes", None)
    if scopes is not None and not isinstance(scopes, (str, bytes)):
        # ``scopes`` is any iterable of scope strings (list, tuple, set, generator, ...).
        # ``str``/``bytes`` are excluded so they are not split into characters.
        try:
            return set(scopes)
        except TypeError:
            return set()  # present but not actually iterable -> malformed, fail closed
    if scope is None and scopes is None:
        # No scope information advertised at all -> unscoped, defer to Wagtail.
        return None
    # A scope attribute is present but malformed (a non-string ``scope``, or a
    # ``str``/``bytes``/non-iterable ``scopes``); fail closed rather than fall open.
    return set()
```

- [ ] **Step 4: Add the `CAST_EDITOR_SCOPES` setting default**

In `src/cast/appsettings.py`, add to `_DYNAMIC_SETTING_DEFAULTS` (after `"CAST_AUDIO_PLAYER": "podlove",`):

```python
    "CAST_EDITOR_SCOPES": {
        # django-cast deliberately has a single write bucket (create/update are not split),
        # so the standard IndieAuth post-write scopes ``create``/``update`` both satisfy it.
        # ``media`` (IndieAuth's upload-endpoint scope) and other aliases are intentionally
        # NOT bundled here: a site whose issuer uses them maps them in via this setting.
        "write": {"write", "create", "update"},
        "publish": {"publish"},
    },
```

And add to the `TYPE_CHECKING` block (after `CAST_AUDIO_PLAYER: str`):

```python
    CAST_EDITOR_SCOPES: dict[str, set[str]]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/api_editor_test.py::TestEditorScopeReader -v`
Expected: PASS (8 passed).

- [ ] **Step 6: Sanity-check the setting reads back**

Run: `python -c "import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','tests.settings'); django.setup(); from cast import appsettings; print(appsettings.CAST_EDITOR_SCOPES)"`
Expected: prints the dict with `write` and `publish` keys. (If `tests.settings` is not the settings module, use the one in `pyproject.toml`/`tox.ini` `DJANGO_SETTINGS_MODULE`.)

- [ ] **Step 7: Commit**

```bash
git add src/cast/api/editor/scopes.py src/cast/appsettings.py tests/api_editor_test.py
git commit -m "# Add editor API scope reader and CAST_EDITOR_SCOPES setting"
```

---

### Task 2: `HasEditorScope` permission class

**Files:**
- Modify: `src/cast/api/editor/scopes.py`
- Test: `tests/api_editor_test.py` (new `TestHasEditorScope` class)

**Interfaces:**
- Consumes: `get_request_scopes`, `_REQUIRED_SCOPE_UNSET` (Task 1); `appsettings.CAST_EDITOR_SCOPES`; `EditorFlatError` from `cast.api.editor.errors`.
- Produces: `cast.api.editor.scopes.HasEditorScope` — a DRF `BasePermission`. `has_permission(request, view)` returns `True` when allowed and raises `EditorFlatError("insufficient_scope", ..., status_code=403)` when the token lacks the required scope or a served method is undeclared. It reads `view.required_scopes: dict[str, str | None]`.

- [ ] **Step 1: Write the failing test**

Add to `tests/api_editor_test.py`. These use lightweight stand-ins for `request`/`view` (DRF permissions only touch `request.method`, `request.auth`, and `view.required_scopes`):

```python
class TestHasEditorScope:
    def _request(self, method, auth):
        return type("Req", (), {"method": method, "auth": auth})()

    def _view(self, required_scopes):
        return type("View", (), {"required_scopes": required_scopes})()

    def test_options_is_allowed_without_declaration(self):
        from cast.api.editor.scopes import HasEditorScope

        perm = HasEditorScope()
        assert perm.has_permission(self._request("OPTIONS", None), self._view({})) is True

    def test_none_scope_method_is_allowed(self):
        from cast.api.editor.scopes import HasEditorScope

        perm = HasEditorScope()
        assert perm.has_permission(self._request("GET", None), self._view({"GET": None})) is True

    def test_undeclared_method_fails_closed(self):
        from cast.api.editor.errors import EditorFlatError
        from cast.api.editor.scopes import HasEditorScope

        perm = HasEditorScope()
        with pytest.raises(EditorFlatError) as exc:
            perm.has_permission(self._request("PATCH", None), self._view({"GET": None}))
        assert exc.value.code_text == "insufficient_scope"
        assert exc.value.status_code == 403

    def test_session_request_allows_write(self):
        from cast.api.editor.scopes import HasEditorScope

        perm = HasEditorScope()
        # request.auth is None (session) -> defer to Wagtail
        assert perm.has_permission(self._request("POST", None), self._view({"POST": "write"})) is True

    def test_unscoped_token_allows_write(self):
        from cast.api.editor.scopes import HasEditorScope

        perm = HasEditorScope()
        token = type("Tok", (), {})()  # no scope/scopes attribute
        assert perm.has_permission(self._request("POST", token), self._view({"POST": "write"})) is True

    def test_scoped_token_missing_scope_is_denied(self):
        from cast.api.editor.errors import EditorFlatError
        from cast.api.editor.scopes import HasEditorScope

        perm = HasEditorScope()
        token = type("Tok", (), {"scope": "publish"})()  # has publish, needs write
        with pytest.raises(EditorFlatError) as exc:
            perm.has_permission(self._request("POST", token), self._view({"POST": "write"}))
        assert exc.value.code_text == "insufficient_scope"

    def test_write_scope_allows_write_but_not_publish(self):
        from cast.api.editor.errors import EditorFlatError
        from cast.api.editor.scopes import HasEditorScope

        perm = HasEditorScope()
        token = type("Tok", (), {"scope": "write"})()
        assert perm.has_permission(self._request("POST", token), self._view({"POST": "write"})) is True
        with pytest.raises(EditorFlatError):
            perm.has_permission(self._request("POST", token), self._view({"POST": "publish"}))

    def test_publish_scope_allows_publish(self):
        from cast.api.editor.scopes import HasEditorScope

        perm = HasEditorScope()
        token = type("Tok", (), {"scope": "publish"})()
        assert perm.has_permission(self._request("POST", token), self._view({"POST": "publish"})) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api_editor_test.py::TestHasEditorScope -v`
Expected: FAIL with `ImportError: cannot import name 'HasEditorScope'`.

- [ ] **Step 3: Implement `HasEditorScope`**

Append to `src/cast/api/editor/scopes.py` (add the imports at the top of the file):

```python
from rest_framework import status
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from ... import appsettings
from .errors import EditorFlatError

_NON_SCOPED_METHODS = frozenset({"OPTIONS", "HEAD"})


class HasEditorScope(BasePermission):
    """Enforce the per-method ``required_scopes`` mapping against ``request.auth`` scopes.

    Scope is necessary, not sufficient — the view body still runs Wagtail permission
    checks. Session auth (``request.auth is None``) and unscoped tokens defer to those
    Wagtail checks. A served method missing a ``required_scopes`` entry fails closed.
    """

    message = "Your token lacks the scope required for this action."

    def has_permission(self, request: Request, view: APIView) -> bool:
        if request.method in _NON_SCOPED_METHODS:
            return True
        required = getattr(view, "required_scopes", {}).get(request.method, _REQUIRED_SCOPE_UNSET)
        if required is _REQUIRED_SCOPE_UNSET:
            # An editor method without an explicit scope declaration is a configuration
            # error; fail closed so a forgotten declaration can never bypass enforcement.
            raise EditorFlatError(
                "insufficient_scope",
                "This action has no configured scope requirement.",
                status_code=status.HTTP_403_FORBIDDEN,
            )
        if required is None:
            return True
        scopes = get_request_scopes(request.auth)
        if scopes is None:
            # Unscoped token or session auth: defer to Wagtail permissions.
            return True
        accepted = appsettings.CAST_EDITOR_SCOPES.get(required, set())
        if scopes & accepted:
            return True
        raise EditorFlatError(
            "insufficient_scope",
            f"This action requires the {required!r} scope.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/api_editor_test.py::TestHasEditorScope -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add src/cast/api/editor/scopes.py tests/api_editor_test.py
git commit -m "# Add HasEditorScope permission class"
```

---

### Task 3: Wire scope enforcement into the editor views

**Files:**
- Modify: `src/cast/api/editor/views.py` (import `HasEditorScope`; add `required_scopes` to `EditorAPIView` and every concrete view; append `HasEditorScope` to `permission_classes`)
- Modify: `src/cast/api/editor/media.py` (add `required_scopes` to the three media list/create views and the collections view)
- Test: `tests/api_editor_test.py` (new `TestEditorViewScopeDeclarations` guard)

**Interfaces:**
- Consumes: `HasEditorScope` (Task 2).
- Produces: every editor view class exposes `required_scopes: dict[str, str | None]`. `EditorAPIView.permission_classes == (IsAuthenticated, HasWagtailAdminAccess, HasEditorScope)`.

- [ ] **Step 1: Write the failing guard test**

Add to `tests/api_editor_test.py`:

```python
class TestEditorViewScopeDeclarations:
    pytestmark = pytest.mark.django_db

    def _editor_views(self):
        from cast.api import urls as api_urls

        views = {}
        for pattern in api_urls.urlpatterns:
            name = getattr(pattern, "name", None) or ""
            if not name.startswith("editor_"):
                continue
            cls = getattr(pattern.callback, "cls", None)
            if cls is not None:
                views[name] = cls
        return views

    def test_found_editor_views(self):
        # Guards the guard: make sure the URLconf scan actually finds the views.
        assert "editor_post_create" in self._editor_views()
        assert "editor_episode_publish" in self._editor_views()

    def test_every_served_method_declares_a_required_scope(self):
        valid = {None, "write", "publish"}
        skipped = {"options", "head", "trace"}
        for name, cls in self._editor_views().items():
            methods = [m for m in cls.http_method_names if m not in skipped and hasattr(cls, m)]
            assert methods, f"{name}: no handler methods found"
            for method in methods:
                key = method.upper()
                assert key in cls.required_scopes, f"{name} ({cls.__name__}) does not declare scope for {key}"
                assert cls.required_scopes[key] in valid, f"{name}: bad scope value for {key}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api_editor_test.py::TestEditorViewScopeDeclarations -v`
Expected: FAIL — `AttributeError`/`assert` because views do not yet declare `required_scopes`.

- [ ] **Step 3: Add `HasEditorScope` to the base view**

In `src/cast/api/editor/views.py`, update the imports and `EditorAPIView`:

```python
from .scopes import HasEditorScope
```

```python
class EditorAPIView(APIView):
    """Base view for the content editing API; renders structured error envelopes."""

    permission_classes = (IsAuthenticated, HasWagtailAdminAccess, HasEditorScope)
    required_scopes: dict[str, str | None] = {}

    def get_exception_handler(self) -> Callable[..., Any]:
        return editor_exception_handler
```

- [ ] **Step 4: Declare `required_scopes` on every concrete view in `views.py`**

Add a `required_scopes` class attribute to each view (place it as the first line of each class body):

```python
class ParentsListView(EditorAPIView):
    required_scopes = {"GET": None}
```

```python
class PostCreateView(PostEditorMixin, EditorAPIView):
    required_scopes = {"POST": "write"}
```

```python
class PostDetailView(PostEditorMixin, EditorAPIView):
    required_scopes = {"GET": None, "PATCH": "write"}
```

```python
class PostPublishView(PostEditorMixin, EditorAPIView):
    required_scopes = {"POST": "publish"}
```

```python
class EpisodeCreateView(EpisodeEditorMixin, EditorAPIView):
    required_scopes = {"POST": "write"}
```

```python
class EpisodeDetailView(EpisodeEditorMixin, EditorAPIView):
    required_scopes = {"GET": None, "PATCH": "write"}
```

```python
class EpisodePublishView(EpisodeEditorMixin, EditorAPIView):
    required_scopes = {"POST": "publish"}
```

- [ ] **Step 5: Declare `required_scopes` on the media views**

In `src/cast/api/editor/media.py`, add to each class body:

```python
class EditorImageListCreateView(EditorMediaListMixin, EditorAPIView):
    required_scopes = {"GET": None, "POST": "write"}
```

```python
class EditorAudioListCreateView(EditorMediaListMixin, EditorAPIView):
    required_scopes = {"GET": None, "POST": "write"}
```

```python
class EditorVideoListCreateView(EditorMediaListMixin, EditorAPIView):
    required_scopes = {"GET": None, "POST": "write"}
```

```python
class EditorMediaCollectionsView(EditorAPIView):
    required_scopes = {"GET": None}
```

- [ ] **Step 6: Run the guard test to verify it passes**

Run: `python -m pytest tests/api_editor_test.py::TestEditorViewScopeDeclarations -v`
Expected: PASS (2 passed).

- [ ] **Step 7: Run the full editor module to confirm no regression**

Run: `python -m pytest tests/api_editor_test.py -q`
Expected: all pass. Existing tests use `force_authenticate(user=...)` (session, `request.auth is None`), so `HasEditorScope` allows and Wagtail checks are unchanged.

- [ ] **Step 8: Commit**

```bash
git add src/cast/api/editor/views.py src/cast/api/editor/media.py tests/api_editor_test.py
git commit -m "# Enforce editor API scopes via per-method required_scopes"
```

---

### Task 4: End-to-end scope enforcement tests with a fake scoped token

**Files:**
- Test: `tests/api_editor_test.py` (new `TestEditorScopeEnforcement` class)

**Interfaces:**
- Consumes: the wired views (Task 3). Uses DRF `api_client.force_authenticate(user=..., token=...)`, which sets `request.auth` to the given token object without configuring a real authentication backend.

- [ ] **Step 1: Write the failing tests**

Add to `tests/api_editor_test.py`:

```python
class _FakeScopedToken:
    def __init__(self, scope: str):
        self.scope = scope


class TestEditorScopeEnforcement:
    pytestmark = pytest.mark.django_db

    def _create_draft(self, api_client, blog, user):
        api_client.force_authenticate(user=user)
        url = reverse("cast:api:editor_post_create")
        payload = {
            "parent": {"id": blog.id},
            "title": "Scope draft",
            "slug": "scope-draft",
            "tags": [],
            "overview": [{"type": "heading", "value": "Notes"}],
        }
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 201, response.content
        return response.json()

    def test_session_request_can_read(self, api_client, blog, admin_user):
        created = self._create_draft(api_client, blog, admin_user)
        # session auth: request.auth is None -> scope layer defers to Wagtail
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})
        assert api_client.get(url, format="json").status_code == 200

    def test_unscoped_token_can_write(self, api_client, blog, admin_user):
        api_client.force_authenticate(user=admin_user, token=type("Tok", (), {})())
        url = reverse("cast:api:editor_post_create")
        payload = {
            "parent": {"id": blog.id},
            "title": "Unscoped write",
            "slug": "unscoped-write",
            "tags": [],
            "overview": [{"type": "heading", "value": "Notes"}],
        }
        assert api_client.post(url, payload, format="json").status_code == 201

    def test_write_scope_can_create(self, api_client, blog, admin_user):
        api_client.force_authenticate(user=admin_user, token=_FakeScopedToken("write"))
        url = reverse("cast:api:editor_post_create")
        payload = {
            "parent": {"id": blog.id},
            "title": "Write scope",
            "slug": "write-scope",
            "tags": [],
            "overview": [{"type": "heading", "value": "Notes"}],
        }
        assert api_client.post(url, payload, format="json").status_code == 201

    def test_missing_scope_is_403_insufficient_scope(self, api_client, blog, admin_user):
        # Token carries 'publish' but creating requires 'write'.
        api_client.force_authenticate(user=admin_user, token=_FakeScopedToken("publish"))
        url = reverse("cast:api:editor_post_create")
        payload = {
            "parent": {"id": blog.id},
            "title": "No write scope",
            "slug": "no-write-scope",
            "tags": [],
            "overview": [{"type": "heading", "value": "Notes"}],
        }
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 403
        assert response.json()["code"] == "insufficient_scope"
        assert not Post.objects.filter(slug="no-write-scope").exists()

    def test_write_scope_cannot_publish(self, api_client, blog, admin_user):
        created = self._create_draft(api_client, blog, admin_user)
        api_client.force_authenticate(user=admin_user, token=_FakeScopedToken("write"))
        url = reverse("cast:api:editor_post_publish", kwargs={"pk": created["id"]})
        response = api_client.post(url, {}, format="json")
        assert response.status_code == 403
        assert response.json()["code"] == "insufficient_scope"
        assert Post.objects.get(pk=created["id"]).live is False

    def test_publish_scope_can_publish(self, api_client, blog, admin_user):
        created = self._create_draft(api_client, blog, admin_user)
        api_client.force_authenticate(user=admin_user, token=_FakeScopedToken("publish"))
        url = reverse("cast:api:editor_post_publish", kwargs={"pk": created["id"]})
        response = api_client.post(url, {}, format="json")
        assert response.status_code == 200, response.content
        assert Post.objects.get(pk=created["id"]).live is True

    def test_scoped_token_can_read_without_scope(self, api_client, blog, admin_user):
        created = self._create_draft(api_client, blog, admin_user)
        # A token scoped only for publish can still GET (reads need no scope).
        api_client.force_authenticate(user=admin_user, token=_FakeScopedToken("publish"))
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})
        assert api_client.get(url, format="json").status_code == 200

    def test_cast_editor_scopes_override_is_honoured(self, api_client, blog, admin_user, settings):
        # Rename the write scope to match a site's issuer vocabulary.
        settings.CAST_EDITOR_SCOPES = {"write": {"posts:edit"}, "publish": {"publish"}}
        api_client.force_authenticate(user=admin_user, token=_FakeScopedToken("posts:edit"))
        url = reverse("cast:api:editor_post_create")
        payload = {
            "parent": {"id": blog.id},
            "title": "Custom scope",
            "slug": "custom-scope",
            "tags": [],
            "overview": [{"type": "heading", "value": "Notes"}],
        }
        assert api_client.post(url, payload, format="json").status_code == 201
```

- [ ] **Step 2: Run the tests**

Run: `python -m pytest tests/api_editor_test.py::TestEditorScopeEnforcement -v`
Expected: PASS (8 passed). These exercise behavior already implemented in Task 3, so they should pass without further production changes. If `test_missing_scope_is_403_insufficient_scope` fails because the `admin_user` cannot create (Wagtail perm) regardless of scope, confirm `admin_user` has add permission (the existing `TestEditorPostPublish` suite relies on the same fixture creating drafts) and that the 403 body code is `insufficient_scope` not `permission_denied`.

- [ ] **Step 3: Run the full editor module**

Run: `python -m pytest tests/api_editor_test.py -q`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add tests/api_editor_test.py
git commit -m "# Add end-to-end editor API scope enforcement tests"
```

---

### Task 5: Documentation, release notes, and backlog/PRD status

**Files:**
- Modify: `docs/reference/api.rst` (the "Authorization" section)
- Modify: `docs/releases/0.2.61.rst` (add a release-note bullet)
- Modify: `BACKLOG.md` (move the item out of Research/Shaping; mark implemented)
- Modify: `backlog/2026-06-19-programmatic-content-editing-api.md` (note the slice shipped)

**Interfaces:** none (docs only).

- [ ] **Step 1: Extend the API reference Authorization section**

In `docs/reference/api.rst`, after the per-endpoint Wagtail-permission list, add:

```rst
Scoped-token authorization
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When a request is authenticated by a token that carries OAuth/IndieAuth-style scopes
(a ``scope`` space-separated string or a ``scopes`` iterable on ``request.auth``), the
editor API additionally enforces a per-action scope on top of the Wagtail permission
checks above:

- Read endpoints (all ``GET``) require no scope.
- Create, update, and media-upload endpoints require the ``write`` scope.
- The publish actions require the ``publish`` scope.

Scope is necessary but not sufficient — the Wagtail permission check still applies. A
token that lacks the required scope receives ``403`` with code ``insufficient_scope``.

Session authentication and tokens that carry no scope information are treated as
unscoped and fall back to pure Wagtail permissions, so existing session and DRF
``TokenAuthentication`` setups are unaffected. The accepted scope strings are
configurable via ``CAST_EDITOR_SCOPES`` (default: ``write`` is satisfied by ``write``,
``create``, or ``update``; ``publish`` by ``publish``), letting a site match its token
issuer's vocabulary without code changes. Scopes that mean something narrower in the
issuer's model (for example IndieAuth's ``media`` upload scope) are intentionally not
bundled into ``write`` by default; add them via this setting if your deployment wants
them to grant editor write access.
```

- [ ] **Step 2: Add a release note**

In `docs/releases/0.2.61.rst`, add a bullet (after the episode publish bullet):

```rst
- The editor API now enforces optional per-action scopes for scoped-token
  authentication: reads need no scope, create/update/media uploads need a ``write``
  scope, and the publish actions need a ``publish`` scope, so a token can be restricted
  to draft-only. Session auth and unscoped tokens fall back to pure Wagtail permissions.
  Accepted scope strings are configurable via ``CAST_EDITOR_SCOPES``; a token missing the
  required scope gets ``403 insufficient_scope``. django-cast still imports no
  authentication provider.
```

- [ ] **Step 3: Update BACKLOG.md**

In `BACKLOG.md`, remove the "Editor API scoped-token / IndieAuth scope mapping" entry from `## Research / Shaping` and record completion (the design and implementation both shipped). If `## Next` is empty, leave the existing placeholder; otherwise no Next change is required.

- [ ] **Step 4: Note the slice shipped in the PRD**

In `backlog/2026-06-19-programmatic-content-editing-api.md`, update the resolved scoped-token open-question entry: change the trailing "Implementation slice pending." to "Implemented in 0.2.61 (`HasEditorScope` + `CAST_EDITOR_SCOPES`)."

- [ ] **Step 5: Verify docs build (if the docs toolchain is available)**

Run: `python -m sphinx -b html docs docs/_build/html -q` (or the project's documented docs build command).
Expected: builds without new warnings about the edited files. If the docs toolchain is not installed, skip and note it.

- [ ] **Step 6: Commit**

```bash
git add docs/reference/api.rst docs/releases/0.2.61.rst BACKLOG.md backlog/2026-06-19-programmatic-content-editing-api.md
git commit -m "# Document editor API scope enforcement"
```

---

## Final verification

- [ ] Run the full editor test module: `python -m pytest tests/api_editor_test.py -q` — all pass.
- [ ] Lint/type the changed files: `python -m ruff check src/cast/api/editor/ src/cast/appsettings.py tests/api_editor_test.py` and `python -m mypy src/cast/api/editor/scopes.py src/cast/api/editor/views.py` — clean.
- [ ] Confirm no authentication provider import was added (grep the diff for `indieweb`/`oauth` — there should be none).
