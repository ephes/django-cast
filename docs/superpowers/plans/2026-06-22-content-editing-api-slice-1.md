# Programmatic Content Editing API — Slice 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a session-authenticated DRF write API that lets a trusted client create a draft `Post` under a chosen `Blog`/`Podcast` from a structured `overview` block list, then read that draft back, without touching the Wagtail admin or the database directly.

**Architecture:** A new `src/cast/api/editor/` subpackage adds three endpoints — `GET /api/editor/parents/` (addable blogs), `POST /api/editor/posts/` (create draft), `GET /api/editor/posts/{id}/` (read draft). The API is authentication-mechanism agnostic: views require an authenticated `request.user` (inheriting the project's `DEFAULT_AUTHENTICATION_CLASSES`) and authorize every action with Wagtail page permissions (`permissions_for_user(user).can_add_subpage()` / `.can_edit()`). A pure conversion module maps an author-friendly block list to/from Wagtail StreamField `overview` values; a structured error envelope gives agents field-precise repair paths.

**Tech Stack:** Django + Wagtail + Django REST Framework, pytest (`tests/*_test.py`), factory_boy. Body stored as Wagtail StreamField (`use_json_field=True`).

## Global Constraints

- Tests live in `tests/` and are named `*_test.py` (not `test_*.py`). Run a single test with `python -m pytest tests/<file>_test.py::<Test> -v` and the suite with `python -m pytest -q`. Test settings module is `tests.settings` (already configured in `pyproject.toml`).
- **Do not set `authentication_classes` on any editor view.** Inherit the project default (`SessionAuthentication` + `TokenAuthentication`) so the API stays auth-mechanism agnostic. (Source: `example/example_site/settings/base.py:199-205`.)
- **Do not add or change global DRF settings** (`DEFAULT_PERMISSION_CLASSES`, `DEFAULT_PAGINATION_CLASS`, `EXCEPTION_HANDLER`). Each editor view declares its own `permission_classes`; the structured error envelope is scoped to editor views via `get_exception_handler`.
- Authorization is always a Wagtail page-permission check, never `is_staff` and never an assumption of one blog per site.
- Drafts only: create a page with `live=False`, then `save_revision(user=...)`. Never publish in this slice.
- Supported `overview` block types in this slice: `heading`, `paragraph`, `code`, `image`, `gallery`. Reject `embed`, `video`, `audio`, and unknown types with a structured error (deferred to a later slice).
- Match existing API conventions: URL names resolve as `cast:api:<name>` (`src/cast/api/urls.py`, `app_name = "api"`); follow the view style in `src/cast/api/views.py`.
- Frequent commits: one commit per task, after its tests pass.

## File Structure

- Create `src/cast/api/editor/__init__.py` — empty package marker.
- Create `src/cast/api/editor/errors.py` — `EditorValidationError`, `EditorPermissionDenied`, `editor_exception_handler`. One responsibility: the structured error envelope.
- Create `src/cast/api/editor/body.py` — pure functions `author_blocks_to_overview()` and `overview_to_author_blocks()`. One responsibility: block-list ⇄ StreamField conversion. No HTTP, no DB writes (only image-existence reads).
- Create `src/cast/api/editor/serializers.py` — DRF serializers for parents output and post create/read scalar metadata.
- Create `src/cast/api/editor/views.py` — `EditorAPIView` base (wires the exception handler), `ParentsListView`, `PostCreateView`, `PostDetailView`.
- Modify `src/cast/api/urls.py` — add the three `editor/...` routes.
- Create `tests/api_editor_test.py` — all tests for the slice.
- Modify `docs/releases/0.2.61.rst` and `docs/reference/api.rst` — release note + API reference.

---

### Task 1: Structured error envelope

**Files:**
- Create: `src/cast/api/editor/__init__.py`
- Create: `src/cast/api/editor/errors.py`
- Test: `tests/api_editor_test.py`

**Interfaces:**
- Produces:
  - `EditorValidationError(errors: dict[str, list[dict]])` — DRF `APIException` subclass; `errors` maps a field path (e.g. `"overview.3.value.1.id"`) to a list of `{"code": str, "message": str}`. Has attribute `.error_map`.
  - `EditorPermissionDenied(detail: str, *, parent_id: int | None = None)` — DRF `APIException` subclass (status 403) with `.detail_text` and `.parent_id`.
  - `editor_exception_handler(exc, context) -> rest_framework.response.Response | None` — renders `EditorValidationError`, `EditorPermissionDenied`, **and DRF's own `ValidationError`** (raised by serializer field validation, e.g. a missing `parent`/`title`) into the documented `validation_error` envelope so field-level and custom validation share one machine-readable shape; delegates everything else to DRF's default handler.

- [ ] **Step 1: Create the package marker**

Create `src/cast/api/editor/__init__.py` (empty file).

- [ ] **Step 2: Write the failing test**

Add to `tests/api_editor_test.py`:

```python
import pytest
from rest_framework import status

from cast.api.editor.errors import (
    EditorPermissionDenied,
    EditorValidationError,
    editor_exception_handler,
)


class TestEditorExceptionHandler:
    def test_validation_error_renders_envelope(self):
        exc = EditorValidationError(
            {"overview.3.value.1.id": [{"code": "not_found", "message": "Image 789 does not exist."}]}
        )
        response = editor_exception_handler(exc, {})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data == {
            "code": "validation_error",
            "errors": {
                "overview.3.value.1.id": [{"code": "not_found", "message": "Image 789 does not exist."}]
            },
        }

    def test_permission_denied_renders_envelope(self):
        exc = EditorPermissionDenied("You cannot add posts under this page.", parent_id=123)
        response = editor_exception_handler(exc, {})
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data == {
            "code": "permission_denied",
            "detail": "You cannot add posts under this page.",
            "parent_id": 123,
        }

    def test_drf_validation_error_mapped_to_envelope(self):
        from rest_framework.exceptions import ErrorDetail, ValidationError

        exc = ValidationError({"title": [ErrorDetail("This field is required.", code="required")]})
        response = editor_exception_handler(exc, {})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["code"] == "validation_error"
        assert response.data["errors"]["title"][0] == {
            "code": "required",
            "message": "This field is required.",
        }

    def test_other_exceptions_delegate_to_default(self):
        from rest_framework.exceptions import NotAuthenticated

        response = editor_exception_handler(NotAuthenticated(), {})
        assert response is not None
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `python -m pytest tests/api_editor_test.py::TestEditorExceptionHandler -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cast.api.editor.errors'`.

- [ ] **Step 4: Write the implementation**

Create `src/cast/api/editor/errors.py`:

```python
from __future__ import annotations

from typing import Any

from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


class EditorValidationError(APIException):
    """Field-precise validation failure rendered as the editor validation envelope."""

    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, error_map: dict[str, list[dict[str, str]]]) -> None:
        self.error_map = error_map
        super().__init__(detail="validation_error")


class EditorPermissionDenied(APIException):
    """Authorization failure against a Wagtail page permission."""

    status_code = status.HTTP_403_FORBIDDEN

    def __init__(self, detail: str, *, parent_id: int | None = None) -> None:
        self.detail_text = detail
        self.parent_id = parent_id
        super().__init__(detail=detail)


def _flatten_drf_errors(detail: Any, prefix: str = "") -> dict[str, list[dict[str, str]]]:
    """Flatten a DRF ValidationError detail into {dotted.path: [{code, message}]}."""
    flat: dict[str, list[dict[str, str]]] = {}
    if isinstance(detail, dict):
        for key, value in detail.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            for sub_path, items in _flatten_drf_errors(value, path).items():
                flat.setdefault(sub_path, []).extend(items)
    elif isinstance(detail, list):
        leaves = [d for d in detail if not isinstance(d, (dict, list))]
        nested = [d for d in detail if isinstance(d, (dict, list))]
        if leaves:
            flat.setdefault(prefix, []).extend(
                {"code": getattr(d, "code", "invalid"), "message": str(d)} for d in leaves
            )
        for index, item in enumerate(nested):
            for sub_path, items in _flatten_drf_errors(item, f"{prefix}.{index}").items():
                flat.setdefault(sub_path, []).extend(items)
    else:
        flat.setdefault(prefix, []).append(
            {"code": getattr(detail, "code", "invalid"), "message": str(detail)}
        )
    return flat


def editor_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    if isinstance(exc, EditorValidationError):
        return Response(
            {"code": "validation_error", "errors": exc.error_map},
            status=exc.status_code,
        )
    if isinstance(exc, EditorPermissionDenied):
        return Response(
            {"code": "permission_denied", "detail": exc.detail_text, "parent_id": exc.parent_id},
            status=exc.status_code,
        )
    if isinstance(exc, DRFValidationError):
        return Response(
            {"code": "validation_error", "errors": _flatten_drf_errors(exc.detail)},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return drf_exception_handler(exc, context)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python -m pytest tests/api_editor_test.py::TestEditorExceptionHandler -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add src/cast/api/editor/__init__.py src/cast/api/editor/errors.py tests/api_editor_test.py
git commit -m "Add structured error envelope for content editing API"
```

---

### Task 2: List editable parents endpoint

**Files:**
- Create: `src/cast/api/editor/serializers.py`
- Create: `src/cast/api/editor/views.py`
- Modify: `src/cast/api/urls.py`
- Test: `tests/api_editor_test.py`

**Interfaces:**
- Consumes: `editor_exception_handler` (Task 1).
- Produces:
  - `EditorAPIView` — DRF `APIView` subclass; overrides `get_exception_handler()` to return `editor_exception_handler`. All editor views inherit it.
  - `ParentsListView` — `GET /api/editor/parents/`; `permission_classes = (IsAuthenticated,)`; returns a JSON list of `{"id", "title", "type", "api_url"}` for every `Blog`/`Podcast` the caller may add a child to.
  - URL name `cast:api:editor_parents`.

- [ ] **Step 1: Write the failing test**

Add to `tests/api_editor_test.py`:

```python
from django.urls import reverse

from tests.factories import BlogFactory, UserFactory


class TestEditorParents:
    pytestmark = pytest.mark.django_db

    def test_requires_authentication(self, api_client, db):
        url = reverse("cast:api:editor_parents")
        response = api_client.get(url, format="json")
        assert response.status_code in (401, 403)

    def test_lists_only_addable_blogs(self, api_client, site):
        owner = UserFactory()
        owner._password = "password"
        blog = BlogFactory(owner=owner, title="Owned blog", slug="owned-blog", parent=site.root_page)
        # A second user with no page permissions must not see the blog.
        other = UserFactory()
        api_client.force_authenticate(user=other)
        url = reverse("cast:api:editor_parents")
        empty = api_client.get(url, format="json").json()
        assert all(entry["id"] != blog.id for entry in empty)

    def test_superuser_sees_blog_with_type_and_api_url(self, api_client, blog, django_user_model):
        admin = django_user_model.objects.create_superuser(
            username="root", email="root@example.com", password="password"
        )
        api_client.force_authenticate(user=admin)
        url = reverse("cast:api:editor_parents")
        data = api_client.get(url, format="json").json()
        entry = next(e for e in data if e["id"] == blog.id)
        assert entry["title"] == blog.title
        assert entry["type"] == "cast.Blog"
        assert entry["api_url"].endswith("/editor/posts/")  # create endpoint hint

    def test_lists_podcast_with_specific_type(self, api_client, podcast, django_user_model):
        admin = django_user_model.objects.create_superuser(
            username="root2", email="root2@example.com", password="password"
        )
        api_client.force_authenticate(user=admin)
        url = reverse("cast:api:editor_parents")
        data = api_client.get(url, format="json").json()
        entry = next(e for e in data if e["id"] == podcast.id)
        assert entry["type"] == "cast.Podcast"
```

Note: the `blog` and `site` fixtures come from `tests/conftest.py`. `force_authenticate` bypasses login and works regardless of auth class — exactly the agnostic behavior we want to assert.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/api_editor_test.py::TestEditorParents -v`
Expected: FAIL — `cast:api:editor_parents` is not a registered URL (`NoReverseMatch`).

- [ ] **Step 3: Create the serializer**

Create `src/cast/api/editor/serializers.py`:

```python
from __future__ import annotations

from rest_framework import serializers


class ParentSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    title = serializers.CharField(read_only=True)
    type = serializers.CharField(read_only=True)
    api_url = serializers.CharField(read_only=True)
```

- [ ] **Step 4: Create the views**

Create `src/cast/api/editor/views.py`:

```python
from __future__ import annotations

from typing import Any, Callable

from django.urls import reverse
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ...models import Blog
from .errors import editor_exception_handler
from .serializers import ParentSerializer


class EditorAPIView(APIView):
    """Base view for the content editing API; renders structured error envelopes."""

    def get_exception_handler(self) -> Callable[..., Any]:
        return editor_exception_handler


class ParentsListView(EditorAPIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        user = request.user
        api_url = reverse("cast:api:editor_post_create")
        parents = []
        # Blog.objects includes Podcast rows: Podcast is concrete MTI over Blog
        # (Podcast has a blog_ptr), so .specific() resolves each row to its
        # Blog/Podcast type and both are listed.
        for blog in Blog.objects.all().specific():
            if blog.permissions_for_user(user).can_add_subpage():
                parents.append(
                    {
                        "id": blog.id,
                        "title": blog.title,
                        "type": blog._meta.label,  # "cast.Blog" or "cast.Podcast"
                        "api_url": api_url,
                    }
                )
        return Response(ParentSerializer(parents, many=True).data)
```

- [ ] **Step 5: Wire the URL**

In `src/cast/api/urls.py`, add `from .editor import views as editor_views` near the existing `from . import views` import. The file already imports `path` and `re_path` (`from django.urls import include, path, re_path`), so no `django.urls` import change is needed. Then add inside `urlpatterns` (before the `wagtail/` include):

```python
    # content editing API (editor)
    path("editor/parents/", editor_views.ParentsListView.as_view(), name="editor_parents"),
    path("editor/posts/", editor_views.PostCreateView.as_view(), name="editor_post_create"),
    re_path(r"^editor/posts/(?P<pk>\d+)/?$", editor_views.PostDetailView.as_view(), name="editor_post_detail"),
```

`PostCreateView`/`PostDetailView` are added in later tasks. To keep this task runnable in isolation, also add minimal placeholders to `src/cast/api/editor/views.py` now:

```python
class PostCreateView(EditorAPIView):
    permission_classes = (IsAuthenticated,)


class PostDetailView(EditorAPIView):
    permission_classes = (IsAuthenticated,)
```

(They are fleshed out in Tasks 5 and 6.)

- [ ] **Step 6: Run the test to verify it passes**

Run: `python -m pytest tests/api_editor_test.py::TestEditorParents -v`
Expected: PASS (4 passed).

- [ ] **Step 7: Commit**

```bash
git add src/cast/api/editor/serializers.py src/cast/api/editor/views.py src/cast/api/urls.py tests/api_editor_test.py
git commit -m "Add editable-parents endpoint to content editing API"
```

---

### Task 3: Author block list → StreamField overview conversion

**Files:**
- Create: `src/cast/api/editor/body.py`
- Test: `tests/api_editor_test.py`

**Interfaces:**
- Consumes: `EditorValidationError` (Task 1).
- Produces:
  - `author_blocks_to_overview(blocks: list[dict], *, path_prefix: str = "overview") -> list[dict]` — returns the internal StreamField `overview` value (a list of `{"type", "value"[, "id"]}` dicts ready to assign under the `overview` section). Raises `EditorValidationError` aggregating every problem with field-precise paths.
  - `SUPPORTED_OVERVIEW_BLOCKS: frozenset[str]` = `{"heading", "paragraph", "code", "image", "gallery"}`.

Author-facing block shapes (canonical input):

| type | author `value` | internal `value` |
|---|---|---|
| `heading` | `str` | `str` (unchanged) |
| `paragraph` | HTML `str` | HTML `str` (unchanged) |
| `code` | `{"language": str, "source": str}` | same dict |
| `image` | `{"id": int}` | `int` (the image pk) |
| `gallery` | `[{"id": int}, ...]` | `{"layout": "default", "gallery": [{"id": <uuid>, "type": "item", "value": int}, ...]}` |

- [ ] **Step 1: Write the failing tests**

Add to `tests/api_editor_test.py`:

```python
import pytest

from cast.api.editor.body import SUPPORTED_OVERVIEW_BLOCKS, author_blocks_to_overview
from cast.api.editor.errors import EditorValidationError


class TestAuthorBlocksToOverview:
    pytestmark = pytest.mark.django_db

    def test_supported_block_set(self):
        assert SUPPORTED_OVERVIEW_BLOCKS == frozenset(
            {"heading", "paragraph", "code", "image", "gallery"}
        )

    def test_heading_paragraph_code_pass_through(self):
        result = author_blocks_to_overview(
            [
                {"type": "heading", "value": "Notes"},
                {"type": "paragraph", "value": "<p>Shipped.</p>"},
                {"type": "code", "value": {"language": "python", "source": "print('hi')"}},
            ]
        )
        assert result == [
            {"type": "heading", "value": "Notes"},
            {"type": "paragraph", "value": "<p>Shipped.</p>"},
            {"type": "code", "value": {"language": "python", "source": "print('hi')"}},
        ]

    def test_image_block_resolves_to_pk(self, image):
        result = author_blocks_to_overview([{"type": "image", "value": {"id": image.id}}])
        assert result == [{"type": "image", "value": image.id}]

    def test_gallery_block_builds_layout_struct(self, image):
        result = author_blocks_to_overview([{"type": "gallery", "value": [{"id": image.id}]}])
        assert result[0]["type"] == "gallery"
        struct = result[0]["value"]
        assert struct["layout"] == "default"
        assert len(struct["gallery"]) == 1
        item = struct["gallery"][0]
        assert item["type"] == "item"
        assert item["value"] == image.id
        assert isinstance(item["id"], str) and len(item["id"]) > 0

    def test_unsupported_type_reports_path(self):
        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview([{"type": "video", "value": {"id": 1}}])
        assert "overview.0.type" in excinfo.value.error_map
        assert excinfo.value.error_map["overview.0.type"][0]["code"] == "unsupported_block_type"

    def test_code_missing_language_reports_path(self):
        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview([{"type": "code", "value": {"source": "x"}}])
        assert "overview.0.value.language" in excinfo.value.error_map

    def test_missing_image_reports_nested_path(self):
        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview(
                [
                    {"type": "heading", "value": "h"},
                    {"type": "gallery", "value": [{"id": 999999}]},
                ]
            )
        assert "overview.1.value.0.id" in excinfo.value.error_map
        assert excinfo.value.error_map["overview.1.value.0.id"][0]["code"] == "not_found"

    def test_all_errors_aggregated(self):
        with pytest.raises(EditorValidationError) as excinfo:
            author_blocks_to_overview(
                [
                    {"type": "bogus", "value": 1},
                    {"type": "image", "value": {"id": 888888}},
                ]
            )
        assert set(excinfo.value.error_map) == {"overview.0.type", "overview.1.value.id"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/api_editor_test.py::TestAuthorBlocksToOverview -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cast.api.editor.body'`.

- [ ] **Step 3: Write the implementation**

Create `src/cast/api/editor/body.py`:

```python
from __future__ import annotations

import uuid
from typing import Any

from wagtail.images import get_image_model

from .errors import EditorValidationError

SUPPORTED_OVERVIEW_BLOCKS = frozenset({"heading", "paragraph", "code", "image", "gallery"})


def _image_exists(image_id: Any) -> bool:
    if not isinstance(image_id, int) or isinstance(image_id, bool):
        return False
    return get_image_model().objects.filter(pk=image_id).exists()


def author_blocks_to_overview(blocks: list[dict], *, path_prefix: str = "overview") -> list[dict]:
    """Convert an author-facing block list into a Wagtail ``overview`` StreamField value.

    Raises :class:`EditorValidationError` aggregating every problem with a field-precise path.
    """
    errors: dict[str, list[dict[str, str]]] = {}
    result: list[dict] = []

    if not isinstance(blocks, list):
        raise EditorValidationError(
            {path_prefix: [{"code": "invalid", "message": "overview must be a list of blocks."}]}
        )

    for index, block in enumerate(blocks):
        base = f"{path_prefix}.{index}"
        if not isinstance(block, dict) or "type" not in block:
            errors[f"{base}.type"] = [{"code": "required", "message": "Each block needs a 'type'."}]
            continue
        block_type = block.get("type")
        value = block.get("value")

        if block_type not in SUPPORTED_OVERVIEW_BLOCKS:
            errors[f"{base}.type"] = [
                {"code": "unsupported_block_type", "message": f"Block type {block_type!r} is not supported."}
            ]
            continue

        if block_type in ("heading", "paragraph"):
            if not isinstance(value, str):
                errors[f"{base}.value"] = [{"code": "invalid", "message": "Expected a string value."}]
                continue
            result.append({"type": block_type, "value": value})

        elif block_type == "code":
            if not isinstance(value, dict):
                errors[f"{base}.value"] = [{"code": "invalid", "message": "Expected an object value."}]
                continue
            block_errors = False
            for key in ("language", "source"):
                if not isinstance(value.get(key), str) or not value.get(key):
                    errors[f"{base}.value.{key}"] = [
                        {"code": "required", "message": f"Code block '{key}' is required."}
                    ]
                    block_errors = True
            if block_errors:
                continue
            result.append(
                {"type": "code", "value": {"language": value["language"], "source": value["source"]}}
            )

        elif block_type == "image":
            image_id = value.get("id") if isinstance(value, dict) else None
            if not _image_exists(image_id):
                errors[f"{base}.value.id"] = [
                    {"code": "not_found", "message": f"Image {image_id} does not exist."}
                ]
                continue
            result.append({"type": "image", "value": image_id})

        elif block_type == "gallery":
            if not isinstance(value, list) or not value:
                errors[f"{base}.value"] = [
                    {"code": "invalid", "message": "Gallery value must be a non-empty list of image refs."}
                ]
                continue
            items = []
            gallery_ok = True
            for img_index, ref in enumerate(value):
                image_id = ref.get("id") if isinstance(ref, dict) else None
                if not _image_exists(image_id):
                    errors[f"{base}.value.{img_index}.id"] = [
                        {"code": "not_found", "message": f"Image {image_id} does not exist."}
                    ]
                    gallery_ok = False
                    continue
                items.append({"id": str(uuid.uuid4()), "type": "item", "value": image_id})
            if not gallery_ok:
                continue
            result.append({"type": "gallery", "value": {"layout": "default", "gallery": items}})

    if errors:
        raise EditorValidationError(errors)
    return result
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/api_editor_test.py::TestAuthorBlocksToOverview -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add src/cast/api/editor/body.py tests/api_editor_test.py
git commit -m "Add author-block to StreamField overview conversion"
```

---

### Task 4: StreamField overview → author block list (reverse conversion)

**Files:**
- Modify: `src/cast/api/editor/body.py`
- Test: `tests/api_editor_test.py`

**Interfaces:**
- Produces: `overview_to_author_blocks(overview_value: list[dict]) -> list[dict]` — inverse of `author_blocks_to_overview` for the supported block types, so a read endpoint round-trips. Unknown stored block types are skipped (a later slice may render them).

- [ ] **Step 1: Write the failing test**

Add to `tests/api_editor_test.py`:

```python
from cast.api.editor.body import author_blocks_to_overview, overview_to_author_blocks


class TestOverviewToAuthorBlocks:
    pytestmark = pytest.mark.django_db

    def test_round_trip(self, image):
        author = [
            {"type": "heading", "value": "Notes"},
            {"type": "paragraph", "value": "<p>Shipped.</p>"},
            {"type": "code", "value": {"language": "python", "source": "print('hi')"}},
            {"type": "image", "value": {"id": image.id}},
            {"type": "gallery", "value": [{"id": image.id}]},
        ]
        internal = author_blocks_to_overview(author)
        assert overview_to_author_blocks(internal) == author

    def test_unknown_stored_block_is_skipped(self):
        internal = [{"type": "embed", "value": "https://example.com"}, {"type": "heading", "value": "h"}]
        assert overview_to_author_blocks(internal) == [{"type": "heading", "value": "h"}]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/api_editor_test.py::TestOverviewToAuthorBlocks -v`
Expected: FAIL with `ImportError: cannot import name 'overview_to_author_blocks'`.

- [ ] **Step 3: Write the implementation**

Append to `src/cast/api/editor/body.py`:

```python
def overview_to_author_blocks(overview_value: list[dict]) -> list[dict]:
    """Inverse of :func:`author_blocks_to_overview` for supported block types."""
    author: list[dict] = []
    for block in overview_value:
        block_type = block.get("type")
        value = block.get("value")
        if block_type in ("heading", "paragraph"):
            author.append({"type": block_type, "value": value})
        elif block_type == "code":
            author.append(
                {"type": "code", "value": {"language": value["language"], "source": value["source"]}}
            )
        elif block_type == "image":
            author.append({"type": "image", "value": {"id": value}})
        elif block_type == "gallery":
            items = value.get("gallery", []) if isinstance(value, dict) else []
            author.append({"type": "gallery", "value": [{"id": item["value"]} for item in items]})
        # unknown/unsupported stored blocks are skipped in this slice
    return author
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/api_editor_test.py::TestOverviewToAuthorBlocks -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/cast/api/editor/body.py tests/api_editor_test.py
git commit -m "Add StreamField overview to author-block reverse conversion"
```

---

### Task 5: Create draft post endpoint

**Files:**
- Modify: `src/cast/api/editor/serializers.py`
- Modify: `src/cast/api/editor/views.py`
- Test: `tests/api_editor_test.py`

**Interfaces:**
- Consumes: `author_blocks_to_overview` (Task 3), `EditorValidationError` / `EditorPermissionDenied` (Task 1), `ParentSerializer` URL name `cast:api:editor_post_detail`.
- Produces: `POST /api/editor/posts/` create endpoint. Request body documented in the PRD ("Create Post Request"). On success returns HTTP 201:
  ```json
  {"id", "type": "cast.Post", "title", "slug", "parent": {"id"},
   "latest_revision_id", "live": false, "status": "draft",
   "preview_url", "edit_url", "api_url"}
  ```
  - `PostCreateSerializer` validates scalar metadata: `parent.id` (required int), `title` (required), `slug` (optional, slugified from title if absent), `visible_date` (optional ISO datetime), `cover_image` (optional `{"id", "alt_text"}`), `tags` (optional list of names), `categories` (optional list of `PostCategory` ids), `overview` (required list, passed to the conversion module), `publish` (optional bool; only `false` accepted in this slice).

Behavioral rules:
- Missing required field (`parent`, `parent.id`, `title`, `overview`) → DRF `ValidationError`, which `editor_exception_handler` (Task 1) renders as the same `validation_error` envelope keyed by the dotted field path (e.g. `"parent.id"`, `"title"`). No special-casing needed in the view.
- Parent id not found → `EditorValidationError({"parent": [{"code": "not_found", ...}]})` (400).
- Parent not a `Blog`/`Podcast` → same `not_found`.
- Parent exists but `can_add_subpage()` is false → `EditorPermissionDenied("You cannot add posts under this page.", parent_id=...)` (403).
- `publish: true` → `EditorValidationError({"publish": [{"code": "unsupported", "message": "Publishing is not available in this API version."}]})`.
- Duplicate slug under the parent → `EditorValidationError({"slug": [{"code": "duplicate", ...}]})`.
- Unknown category id → `EditorValidationError({"categories": [{"code": "not_found", ...}]})`.
- Missing cover image → `EditorValidationError({"cover_image.id": [{"code": "not_found", ...}]})`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/api_editor_test.py`:

```python
from cast.models import Post


class TestEditorPostCreate:
    pytestmark = pytest.mark.django_db

    # ``admin_user`` (tests/conftest.py) is a non-superuser Moderator holding
    # GroupPagePermission add_page/change_page/publish_page on the root page, so
    # it has can_add_subpage()/can_edit() on any blog or podcast under the site.
    # Page ownership alone does NOT grant the Wagtail "add" permission, so the
    # blog owner cannot be used as the authorized caller here.

    def _payload(self, parent, **overrides):
        payload = {
            "parent": {"id": parent.id},
            "title": "Weeknotes 2026-25",
            "slug": "weeknotes-2026-25",
            "tags": ["weeknotes"],
            "overview": [
                {"type": "heading", "value": "Notes"},
                {"type": "paragraph", "value": "<p>Shipped the first draft.</p>"},
                {"type": "code", "value": {"language": "python", "source": "print('hi')"}},
            ],
            "publish": False,
        }
        payload.update(overrides)
        return payload

    def test_requires_authentication(self, api_client, blog):
        url = reverse("cast:api:editor_post_create")
        response = api_client.post(url, self._payload(blog), format="json")
        assert response.status_code in (401, 403)

    def test_creates_unpublished_draft(self, api_client, blog, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_create")
        response = api_client.post(url, self._payload(blog), format="json")
        assert response.status_code == 201, response.content
        data = response.json()
        post = Post.objects.get(id=data["id"])
        assert post.live is False
        assert data["status"] == "draft"
        assert data["type"] == "cast.Post"
        assert data["parent"]["id"] == blog.id
        assert data["latest_revision_id"] == post.latest_revision_id
        assert data["edit_url"].endswith(f"/pages/{post.id}/edit/")
        assert data["preview_url"].endswith(f"/pages/{post.id}/view_draft/")
        assert data["api_url"].endswith(f"/editor/posts/{post.id}/")
        assert list(post.tags.values_list("name", flat=True)) == ["weeknotes"]
        # the structured input lands in the overview section
        assert post.body[0].block_type == "overview"

    def test_creates_draft_under_podcast(self, api_client, podcast, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_create")
        response = api_client.post(
            url, self._payload(podcast, slug="weeknotes-pod"), format="json"
        )
        assert response.status_code == 201, response.content
        data = response.json()
        assert data["parent"]["id"] == podcast.id
        assert Post.objects.get(id=data["id"]).get_parent().id == podcast.id

    def test_rejects_caller_without_add_permission(self, api_client, blog):
        stranger = UserFactory()
        api_client.force_authenticate(user=stranger)
        url = reverse("cast:api:editor_post_create")
        response = api_client.post(url, self._payload(blog), format="json")
        assert response.status_code == 403
        assert response.json()["code"] == "permission_denied"

    def test_unknown_parent_is_validation_error(self, api_client, blog, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_create")
        response = api_client.post(url, self._payload(blog, parent={"id": 999999}), format="json")
        assert response.status_code == 400
        body = response.json()
        assert body["code"] == "validation_error"
        assert "parent" in body["errors"]

    def test_missing_required_field_uses_envelope(self, api_client, blog, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_create")
        payload = self._payload(blog)
        del payload["title"]
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 400
        body = response.json()
        assert body["code"] == "validation_error"
        assert "title" in body["errors"]

    def test_publish_true_is_rejected(self, api_client, blog, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_create")
        response = api_client.post(url, self._payload(blog, publish=True), format="json")
        assert response.status_code == 400
        assert "publish" in response.json()["errors"]

    def test_missing_image_returns_precise_path(self, api_client, blog, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_create")
        payload = self._payload(
            blog,
            slug="weeknotes-img",
            overview=[{"type": "gallery", "value": [{"id": 999999}]}],
        )
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 400
        assert "overview.0.value.0.id" in response.json()["errors"]

    def test_duplicate_slug_is_validation_error(self, api_client, blog, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_create")
        first = api_client.post(url, self._payload(blog), format="json")
        assert first.status_code == 201
        second = api_client.post(url, self._payload(blog), format="json")
        assert second.status_code == 400
        assert "slug" in second.json()["errors"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/api_editor_test.py::TestEditorPostCreate -v`
Expected: FAIL — `PostCreateView` has no `post()` handler (405) / returns no body.

- [ ] **Step 3: Extend the serializer**

Append to `src/cast/api/editor/serializers.py`:

```python
class ParentRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()


class CoverImageSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    alt_text = serializers.CharField(required=False, allow_blank=True, default="")


class PostCreateSerializer(serializers.Serializer):
    parent = ParentRefSerializer()
    title = serializers.CharField()
    slug = serializers.SlugField(required=False)
    visible_date = serializers.DateTimeField(required=False)
    cover_image = CoverImageSerializer(required=False)
    tags = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    categories = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)
    overview = serializers.ListField()  # required: the structured overview block list
    publish = serializers.BooleanField(required=False, default=False)
```

- [ ] **Step 4: Implement the create view**

Replace the `PostCreateView` placeholder in `src/cast/api/editor/views.py`. First extend the imports at the top of the file:

```python
import json

from django.utils.text import slugify
from rest_framework import status

from ...models import Post
from ...models.snippets import PostCategory
from wagtail.images import get_image_model
from .body import author_blocks_to_overview
from .errors import EditorPermissionDenied, EditorValidationError
from .serializers import PostCreateSerializer
```

Then implement:

```python
class PostCreateView(EditorAPIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = PostCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = request.user

        if data["publish"]:
            raise EditorValidationError(
                {"publish": [{"code": "unsupported", "message": "Publishing is not available in this API version."}]}
            )

        parent = self._get_parent(data["parent"]["id"])
        if not parent.permissions_for_user(user).can_add_subpage():
            raise EditorPermissionDenied(
                "You cannot add posts under this page.", parent_id=parent.id
            )

        title = data["title"]
        slug = data.get("slug") or slugify(title)
        self._check_unique_slug(parent, slug)

        cover_image, cover_alt_text = self._resolve_cover_image(data.get("cover_image"))
        categories = self._resolve_categories(data["categories"])
        overview_value = author_blocks_to_overview(data["overview"])

        # Assign body as a JSON string (the proven pattern in tests/conftest.py);
        # the StreamField parses it on access. ``overview_value`` is the list of
        # internal block dicts produced by author_blocks_to_overview().
        post = Post(
            title=title,
            slug=slug,
            owner=user,
            live=False,
            cover_image=cover_image,
            cover_alt_text=cover_alt_text,
            body=json.dumps([{"type": "overview", "value": overview_value}]),
        )
        if data.get("visible_date") is not None:
            post.visible_date = data["visible_date"]
        parent.add_child(instance=post)
        if data["tags"]:
            post.tags.add(*data["tags"])
        if categories:
            post.categories.set(categories)
        revision = post.save_revision(user=user)

        return Response(self._serialize(post, parent, revision), status=status.HTTP_201_CREATED)

    # --- helpers -------------------------------------------------------

    def _get_parent(self, parent_id: int):
        from ...models import Blog

        blog = Blog.objects.filter(pk=parent_id).first()
        if blog is None:
            raise EditorValidationError(
                {"parent": [{"code": "not_found", "message": f"Parent {parent_id} does not exist."}]}
            )
        return blog.specific

    def _check_unique_slug(self, parent, slug: str) -> None:
        from wagtail.models import Page

        if Page.objects.child_of(parent).filter(slug=slug).exists():
            raise EditorValidationError(
                {"slug": [{"code": "duplicate", "message": f"Slug {slug!r} is already used here."}]}
            )

    def _resolve_cover_image(self, cover):
        if not cover:
            return None, ""
        image = get_image_model().objects.filter(pk=cover["id"]).first()
        if image is None:
            raise EditorValidationError(
                {"cover_image.id": [{"code": "not_found", "message": f"Image {cover['id']} does not exist."}]}
            )
        return image, cover.get("alt_text", "")

    def _resolve_categories(self, ids):
        if not ids:
            return []
        found = list(PostCategory.objects.filter(pk__in=ids))
        if len(found) != len(set(ids)):
            missing = sorted(set(ids) - {c.pk for c in found})
            raise EditorValidationError(
                {"categories": [{"code": "not_found", "message": f"Unknown category ids: {missing}."}]}
            )
        return found

    def _serialize(self, post, parent, revision) -> dict:
        return {
            "id": post.id,
            "type": post._meta.label,
            "title": post.title,
            "slug": post.slug,
            "parent": {"id": parent.id},
            "latest_revision_id": revision.id,
            "live": post.live,
            "status": "draft",
            "preview_url": reverse("wagtailadmin_pages:view_draft", args=[post.id]),
            "edit_url": reverse("wagtailadmin_pages:edit", args=[post.id]),
            "api_url": reverse("cast:api:editor_post_detail", kwargs={"pk": post.id}),
        }
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/api_editor_test.py::TestEditorPostCreate -v`
Expected: PASS (9 passed).

- [ ] **Step 6: Run the whole editor test module**

Run: `python -m pytest tests/api_editor_test.py -v`
Expected: PASS (all prior tasks still green).

- [ ] **Step 7: Commit**

```bash
git add src/cast/api/editor/serializers.py src/cast/api/editor/views.py tests/api_editor_test.py
git commit -m "Add draft post creation endpoint to content editing API"
```

---

### Task 6: Read draft post endpoint

**Files:**
- Modify: `src/cast/api/editor/views.py`
- Test: `tests/api_editor_test.py`

**Interfaces:**
- Consumes: `overview_to_author_blocks` (Task 4), URL name `cast:api:editor_post_detail` (Task 2).
- Produces: `GET /api/editor/posts/{id}/` returning editable metadata, the normalized `overview` block list, revision metadata, and admin URLs — for drafts the public Wagtail pages API cannot return. Authorization: `can_edit()`. Response:
  ```json
  {"id", "type", "title", "slug", "parent": {"id"}, "visible_date",
   "tags": [...], "categories": [ids], "cover_image": {"id", "alt_text"} | null,
   "overview": [...author blocks...],
   "latest_revision_id", "live", "status",
   "preview_url", "edit_url", "api_url"}
  ```

- [ ] **Step 1: Write the failing tests**

Add to `tests/api_editor_test.py`:

```python
class TestEditorPostDetail:
    pytestmark = pytest.mark.django_db

    def _create(self, api_client, blog, admin_user):
        api_client.force_authenticate(user=admin_user)
        create_url = reverse("cast:api:editor_post_create")
        payload = {
            "parent": {"id": blog.id},
            "title": "Readable draft",
            "slug": "readable-draft",
            "tags": ["weeknotes"],
            "overview": [
                {"type": "heading", "value": "Notes"},
                {"type": "code", "value": {"language": "python", "source": "print('hi')"}},
            ],
        }
        return api_client.post(create_url, payload, format="json").json()

    def test_reads_back_normalized_overview(self, api_client, blog, admin_user):
        created = self._create(api_client, blog, admin_user)
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})
        response = api_client.get(url, format="json")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == created["id"]
        assert data["status"] == "draft"
        assert data["tags"] == ["weeknotes"]
        assert data["overview"] == [
            {"type": "heading", "value": "Notes"},
            {"type": "code", "value": {"language": "python", "source": "print('hi')"}},
        ]

    def test_rejects_caller_without_edit_permission(self, api_client, blog, admin_user):
        created = self._create(api_client, blog, admin_user)
        stranger = UserFactory()
        api_client.force_authenticate(user=stranger)
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})
        response = api_client.get(url, format="json")
        assert response.status_code == 403

    def test_missing_post_returns_404(self, api_client, blog, admin_user):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": 999999})
        response = api_client.get(url, format="json")
        assert response.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/api_editor_test.py::TestEditorPostDetail -v`
Expected: FAIL — `PostDetailView` has no `get()` handler (405).

- [ ] **Step 3: Implement the detail view**

Add `overview_to_author_blocks` to the body import in `src/cast/api/editor/views.py`:

```python
from .body import author_blocks_to_overview, overview_to_author_blocks
```

Add `from django.http import Http404` to the imports, then replace the `PostDetailView` placeholder:

```python
class PostDetailView(EditorAPIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, *args: Any, pk: int, **kwargs: Any) -> Response:
        post = Post.objects.filter(pk=pk).first()
        if post is None:
            raise Http404("Post not found.")
        post = post.specific
        if not post.permissions_for_user(request.user).can_edit():
            raise EditorPermissionDenied("You cannot view this draft.", parent_id=None)

        overview_value = []
        for block in post.body:
            if block.block_type == "overview":
                overview_value = block.value.raw_data
                break

        cover = None
        if post.cover_image_id is not None:
            cover = {"id": post.cover_image_id, "alt_text": post.cover_alt_text}

        return Response(
            {
                "id": post.id,
                "type": post._meta.label,
                "title": post.title,
                "slug": post.slug,
                "parent": {"id": post.get_parent().id},
                "visible_date": post.visible_date,
                "tags": list(post.tags.values_list("name", flat=True)),
                "categories": list(post.categories.values_list("pk", flat=True)),
                "cover_image": cover,
                "overview": overview_to_author_blocks(overview_value),
                "latest_revision_id": post.latest_revision_id,
                "live": post.live,
                "status": "live" if post.live else "draft",
                "preview_url": reverse("wagtailadmin_pages:view_draft", args=[post.id]),
                "edit_url": reverse("wagtailadmin_pages:edit", args=[post.id]),
                "api_url": reverse("cast:api:editor_post_detail", kwargs={"pk": post.id}),
            }
        )
```

Note on `block.value.raw_data`: the `overview` `StreamValue` exposes its stored list of `{"type", "value"}` dicts via `raw_data`; this is the same shape `author_blocks_to_overview` produced and `overview_to_author_blocks` consumes. If `raw_data` is unavailable on the installed Wagtail version, fall back to `[{"type": child.block_type, "value": child.value} for child in block.value]` — but verify the round-trip test still passes, since `child.value` for image/gallery returns resolved objects rather than raw ids.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/api_editor_test.py::TestEditorPostDetail -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the whole editor test module**

Run: `python -m pytest tests/api_editor_test.py -v`
Expected: PASS (all tasks green).

- [ ] **Step 6: Commit**

```bash
git add src/cast/api/editor/views.py tests/api_editor_test.py
git commit -m "Add draft post read endpoint to content editing API"
```

---

### Task 7: Documentation and release notes

**Files:**
- Modify: `docs/releases/0.2.61.rst`
- Modify: `docs/reference/api.rst`
- Modify: `backlog/2026-06-19-programmatic-content-editing-api.md`

**Interfaces:** none (docs only).

- [ ] **Step 1: Add a release note**

In `docs/releases/0.2.61.rst`, add a bullet under the existing list:

```rst
- Added a session-authenticated programmatic content editing API
  (``/api/editor/``). Trusted clients can list the blogs and podcasts they may
  add to (``GET /api/editor/parents/``), create a draft ``Post`` from a
  structured ``overview`` block list (``POST /api/editor/posts/``), and read the
  draft back with normalized authoring source (``GET /api/editor/posts/{id}/``).
  The API stays authentication-mechanism agnostic — it requires an authenticated
  user and authorizes every action with Wagtail page permissions — and never
  publishes: pages are created as drafts via Wagtail revisions. Body blocks
  supported in this slice: heading, paragraph, code, image, and gallery
  (referencing existing images).
```

- [ ] **Step 2: Add an API reference section**

In `docs/reference/api.rst`, add a section documenting the three editor endpoints, the create request shape (copy the "Create Post Request" JSON from the PRD), the structured validation envelope, and the draft-only / Wagtail-permission behavior. Keep the style consistent with the surrounding reference doc.

- [ ] **Step 3: Flip the PRD status**

In `backlog/2026-06-19-programmatic-content-editing-api.md`, update the `Status:` line to record that the first slice is implemented (create + read + parents), and that publish, update/conflict detection, Markdown convenience input, and scoped-token auth remain follow-ups.

- [ ] **Step 4: Build the docs to verify no syntax errors**

Run: `python -m pytest tests/api_editor_test.py -q && echo "tests ok"`
Then, if a docs build is available: `make -C docs html` (optional; skip if Sphinx deps are not installed). Expected: tests pass; docs build emits no errors for the edited files.

- [ ] **Step 5: Commit**

```bash
git add docs/releases/0.2.61.rst docs/reference/api.rst backlog/2026-06-19-programmatic-content-editing-api.md
git commit -m "Document content editing API slice 1"
```

---

## Self-Review

**1. Spec coverage** (against the PRD "First Implementation Slice" and "Test Scenarios"):
- Slice item 1 (session-auth create under selected Blog) → Task 5; auth-agnostic + Wagtail permission → Tasks 2/5/6.
- Slice item 2 (title, slug, visible date, tags, categories, cover image, structured overview, inline image/gallery) → Tasks 3 + 5.
- Slice item 3 (convert block list into overview StreamField, paragraph rich-text HTML + code) → Task 3.
- Slice item 4 (save draft revision, return page id / latest revision id / preview / edit / api urls) → Task 5.
- Slice item 5 (read support incl. normalized overview) → Tasks 4 + 6.
- Slice item 6 (publish remains a separate follow-up) → enforced (publish:true rejected) in Task 5; documented in Task 7.
- Test scenarios — anonymous/unauthorized cannot create (Tasks 2,5,6); both `Blog` and `Podcast` parents work and never assume a site-specific blog (parents query is global and Podcast is included via MTI — covered by `test_lists_podcast_with_specific_type` and `test_creates_draft_under_podcast`); authorization is a real Wagtail page permission, exercised via the `admin_user` fixture rather than page ownership (Tasks 5,6); tags resolved like admin (Task 5); missing image returns structured error (Tasks 3,5); heading/paragraph/code round-trip (Tasks 3,4,6); not published by default (Task 5).
- Deferred by design (not in this plan, called out in PRD/Task 7): PATCH + `409` conflict detection, publish action, Markdown input, IndieAuth/scoped-token auth, embed/video/audio blocks, remote image import.

**2. Placeholder scan:** every code step contains complete code; every test step contains real assertions; no "TBD"/"add validation"/"handle edge cases" left. The one conditional ("if `raw_data` is unavailable…") is an explicit, code-complete fallback with a verification instruction, not a placeholder.

**3. Type consistency:** `author_blocks_to_overview`/`overview_to_author_blocks` signatures match across Tasks 3, 4, 5, 6. `EditorValidationError(error_map)` / `EditorPermissionDenied(detail, parent_id=...)` used consistently with their Task 1 definitions and the `.error_map` / `.detail_text` / `.parent_id` attributes the handler reads. URL names (`editor_parents`, `editor_post_create`, `editor_post_detail`) are consistent between `urls.py` (Task 2) and every `reverse()` call. The create response and the detail response share the same `status`/`live`/`*_url` field names.

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-22-content-editing-api-slice-1.md`.**
</content>
</invoke>
