# Model-Layer Decoupling Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Break the models→views import inversion, make post description rendering stateless, and give media `save()` side effects transactional discipline and explicit opt-outs.

**Architecture:** Three independent slices of the architecture-review model-layer theme (findings M1, H1, H2 in `backlog/2026-07-02-architecture-review.md`). Each preserves public contracts: `HtmxHttpRequest` stays importable from `cast.views`/`cast.views.htmx_helpers`, `Post.get_description` keeps its signature, and `Post.save`/`Video.save` keep default behavior.

**Tech Stack:** Django 4.2–6, Wagtail 7, pytest (+pytest-django), ruff (line length 119), mypy (django-stubs).

## Global Constraints

- Do NOT run `git commit` at any point — all changes stay uncommitted in the working tree.
- The project enforces 100% branch coverage (`just test` fails below 100%); every new branch needs a test.
- Ruff (`uv run ruff check <files>`) and mypy (`uv run mypy`) must stay clean; line length 119.
- TDD: failing test first, watch it fail, implement, watch it pass.
- Do not touch files outside each task's list. The working tree may contain other tasks' uncommitted changes — leave them alone.
- Line numbers below were correct at plan time; always re-locate via the quoted code, not the number.

---

### Task 1: Neutral `HtmxHttpRequest` module (finding M1)

**Files:**
- Create: `src/cast/http_types.py`
- Modify: `src/cast/views/htmx_helpers.py` (re-export), plus every direct importer of `HtmxHttpRequest` outside `views/`: `src/cast/models/pages.py`, `src/cast/models/index_pages.py`, `src/cast/models/repository/builders.py`, `src/cast/models/repository/contexts.py`, `src/cast/feeds.py`, `src/cast/api/views.py`, `src/cast/management/commands/ensure_reference_site.py`, `src/cast/management/commands/styleguide_prefetch.py`
- Test: `tests/models_test.py` (one back-compat identity test)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `cast.http_types.HtmxHttpRequest` — the canonical location; `cast.views.htmx_helpers.HtmxHttpRequest` and `cast.views.HtmxHttpRequest` remain aliases of the same class object (external themes may import from there).

- [ ] **Step 1: Write the failing back-compat test**

Add to `tests/models_test.py` (module level, near the imports/top-level tests):

```python
def test_htmx_http_request_is_importable_from_neutral_module():
    """Models must not depend on the views package for typing (architecture review M1)."""
    from cast.http_types import HtmxHttpRequest as neutral
    from cast.views.htmx_helpers import HtmxHttpRequest as legacy

    assert neutral is legacy
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/models_test.py::test_htmx_http_request_is_importable_from_neutral_module -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cast.http_types'`

- [ ] **Step 3: Create the neutral module**

Create `src/cast/http_types.py` with exactly the current class (moved, not copied — Step 4 removes the original):

```python
from django.http import HttpRequest
from django_htmx.middleware import HtmxDetails


# Typing pattern recommended by django-stubs:
# https://github.com/typeddjango/django-stubs#how-can-i-create-a-httprequest-thats-guaranteed-to-have-an-authenticated-user
class HtmxHttpRequest(HttpRequest):
    cast_site_template_base_dir: str
    htmx: HtmxDetails
```

- [ ] **Step 4: Turn `views/htmx_helpers.py` into a re-export**

Replace the whole file content with:

```python
from cast.http_types import HtmxHttpRequest

__all__ = ["HtmxHttpRequest"]
```

Leave `src/cast/views/__init__.py` untouched — it already re-exports `HtmxHttpRequest` and must keep doing so.

- [ ] **Step 5: Repoint the non-views importers**

In each of these files, change the import of `HtmxHttpRequest` to `from cast.http_types import HtmxHttpRequest` (or the equivalent relative form matching the file's import style, e.g. `from ..http_types import ...` inside `models/`): `src/cast/models/pages.py`, `src/cast/models/index_pages.py`, `src/cast/models/repository/builders.py`, `src/cast/models/repository/contexts.py`, `src/cast/feeds.py`, `src/cast/api/views.py`, `src/cast/management/commands/ensure_reference_site.py`, `src/cast/management/commands/styleguide_prefetch.py`. Only the `HtmxHttpRequest` import changes — if a file imports other names from `..views` on the same line, split the import and keep the rest. Then verify the inversion is gone:

Run: `grep -rn "views import\|views\.htmx" src/cast/models/ src/cast/feeds.py`
Expected: no `HtmxHttpRequest` hits in `src/cast/models/` (other `views` imports, if any remain, are out of scope — note them in the report, don't fix).

- [ ] **Step 6: Run the test and the affected suites**

Run: `uv run pytest tests/models_test.py::test_htmx_http_request_is_importable_from_neutral_module tests/feed_test.py tests/api_test.py -q`
Expected: PASS. Then `uv run ruff check src/cast/ && uv run mypy` — clean.

---

### Task 2: Stateless post description rendering (finding H1 slice)

**Files:**
- Modify: `src/cast/models/pages.py` — `get_description` (~line 624-652), `get_template` (~line 295-301), the `_local_template_name` class attribute (~line 208)
- Test: `tests/post_detail_test.py` or `tests/models_test.py` (put the regression test next to existing detail-rendering tests; check both files and pick the one that already renders a post via `serve`)

**Interfaces:**
- Consumes: nothing from Task 1 (independent — the file overlaps but the edits don't).
- Produces: `Post.get_description(...)` — same signature and return value as today, but side-effect free; `Post.get_template(...)` loses its `_local_template_name` branch (the `local_template_name` keyword parameter remains).

Background: `Post.serve` forwards `**kwargs` to Wagtail's `Page.serve`, which passes them to both `get_template` and `get_context`. `get_template` already accepts `local_template_name` as a keyword; `get_context(self, request, **kwargs)` tolerates extras. So the instance mutation is unnecessary — and it is a real bug: after `get_description()` runs, `self._local_template_name` stays `"post_body.html"` forever, so any later render of the same instance uses the wrong template.

- [ ] **Step 1: Verify the attribute has no other users**

Run: `grep -rn "_local_template_name" src/ tests/`
Expected: exactly three hits, all in `src/cast/models/pages.py` (declaration ~208, `get_template` branch ~296-297, `get_description` assignment ~641). If there are more, STOP and report NEEDS_CONTEXT.

- [ ] **Step 2: Write the failing regression test**

```python
@pytest.mark.django_db
def test_get_description_does_not_leak_template_into_later_renders(client, post):
    """get_description must not mutate instance state (architecture review H1).

    Before the fix, calling get_description left _local_template_name set to
    "post_body.html", so any later render of the same instance used the body
    partial instead of the full post template.
    """
    request = client.get(post.get_url()).wsgi_request
    description = post.get_description(request=request)
    assert description  # sanity: rendering worked
    template_after = post.get_template(request)
    assert template_after.endswith("/post.html")
```

Adapt the request construction to the fixtures actually available in the chosen test module (an existing test that calls `post.serve` or `post.get_description` shows the local idiom — `django.test.RequestFactory` via an existing `rf`/`request` fixture is fine; the `post` fixture exists in `tests/conftest.py`). The essential assertions: after `get_description`, `get_template` returns `.../post.html`, and (second assertion) the returned description is non-empty. Keep both.

- [ ] **Step 3: Run it to verify it fails**

Run: `uv run pytest <chosen module>::test_get_description_does_not_leak_template_into_later_renders -v`
Expected: FAIL — `template_after` ends with `/post_body.html`.

- [ ] **Step 4: Make `get_description` pass the template name as a kwarg**

In `get_description`, replace:

```python
        self._local_template_name = "post_body.html"
        description = self.serve(
            request, render_detail=render_detail, repository=repository, render_for_feed=render_for_feed
        ).rendered_content
```

with:

```python
        description = self.serve(
            request,
            render_detail=render_detail,
            repository=repository,
            render_for_feed=render_for_feed,
            local_template_name="post_body.html",
        ).rendered_content
```

- [ ] **Step 5: Remove the now-dead machinery**

Delete the class attribute `_local_template_name: str | None = None` (~line 208) and in `get_template` delete:

```python
        if self._local_template_name is not None:
            local_template_name = self._local_template_name
```

- [ ] **Step 6: Run the regression test and the rendering suites**

Run: `uv run pytest <chosen module> tests/feed_test.py tests/post_detail_test.py tests/repository_test.py -q`
Expected: PASS (feeds exercise `get_description` heavily; any failure here means `local_template_name` did not reach `get_template` — check `Episode.get_template` (~line 844) also honors the kwarg, since podcast feeds render Episode descriptions; if it doesn't, apply the same kwarg handling there and extend the regression test to an `episode` fixture).

Then `uv run ruff check src/cast/models/pages.py && uv run mypy` — clean.

---

### Task 3: Transactional and opt-out media save side effects (finding H2 slice)

**Files:**
- Modify: `src/cast/models/video.py` (`Video.save`, ~line 183-202), `src/cast/models/pages.py` (`Post.save`, ~line 688-692)
- Test: `tests/models_test.py` (video atomicity; post save opt-outs — put them near existing `Video`/`Post` save tests; check `tests/video_test.py` first and use it if it exists)

**Interfaces:**
- Consumes: nothing from Tasks 1-2 (same-file edits in pages.py are in different methods).
- Produces: `Video.save(*args, poster=True, **kwargs)` — unchanged signature, now atomic like `Audio.save`; `Post.save(*args, sync_media=True, create_renditions=True, **kwargs)` — two new opt-out keywords, defaults preserve today's behavior.

- [ ] **Step 1: Write the failing video atomicity test**

```python
@pytest.mark.django_db
def test_video_save_rolls_back_row_when_poster_generation_fails(monkeypatch, minimal_video_file, user):
    """Video.save enrichment must be all-or-nothing like Audio.save (architecture review H2)."""
    from cast.models import Video

    def boom(self):
        raise RuntimeError("poster generation failed")

    monkeypatch.setattr(Video, "create_poster", boom)
    video = Video(user=user, original=minimal_video_file)
    with pytest.raises(RuntimeError):
        video.save()
    assert Video.objects.count() == 0
```

Use the existing video-file fixture from `tests/conftest.py` (grep for how existing `Video` tests construct instances — there is an established fixture; reuse it, do not hand-roll binary data).

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest <chosen module>::test_video_save_rolls_back_row_when_poster_generation_fails -v`
Expected: FAIL — `Video.objects.count() == 1` (the row survives because nothing wraps the save in a transaction).

- [ ] **Step 3: Make `Video.save` transactional**

Replace the body of `Video.save` with (mirroring `Audio.save`'s structure at `src/cast/models/audio.py:347-378`; `transaction` may need importing from `django.db`):

```python
    def save(self, *args, **kwargs) -> Optional["Video"]:  # type: ignore[override]
        generate_poster = kwargs.pop("poster", True)
        using = kwargs.get("using")
        if generate_poster and not getattr(self.original, "_committed", True):
            validate_video_upload(self.original.file)
        # Keep poster generation and persistence all-or-nothing to avoid
        # partially updated rows when poster creation fails (same discipline
        # as Audio.save).
        with transaction.atomic(using=using):
            # need to save original first - django file handling is driving me nuts
            result = super().save(*args, **kwargs)
            if generate_poster:
                logger.info("generate video poster")
                # generate poster thumbnail by default, but make it optional
                # for recalc management command
                poster_name_before = self.poster.name or ""
                self.create_poster()
                poster_name_after = self.poster.name or ""
                if poster_name_after and poster_name_after != poster_name_before:
                    save_kwargs: dict[str, object] = {"update_fields": ["poster"]}
                    if using is not None:
                        save_kwargs["using"] = using
                    result = super().save(**save_kwargs)
        return result
```

- [ ] **Step 4: Run the atomicity test to verify it passes**

Run: `uv run pytest <chosen module>::test_video_save_rolls_back_row_when_poster_generation_fails -v`
Expected: PASS. Also run the whole video test module — existing poster tests must still pass.

- [ ] **Step 5: Write the failing post save opt-out tests**

```python
@pytest.mark.django_db
def test_post_save_side_effects_can_be_skipped(monkeypatch, post):
    """Post.save media derivation must be skippable for bulk operations (architecture review H2)."""
    import cast.models.pages as pages_module

    sync_calls, rendition_calls = [], []
    monkeypatch.setattr(type(post), "sync_media_ids", lambda self: sync_calls.append(1))
    monkeypatch.setattr(
        pages_module, "create_missing_renditions_for_posts", lambda posts: rendition_calls.append(1)
    )

    post.save(sync_media=False, create_renditions=False)
    assert sync_calls == [] and rendition_calls == []

    post.save()
    assert sync_calls == [1] and rendition_calls == [1]
```

Check how `create_missing_renditions_for_posts` is imported in `pages.py` (module-level `from`-import means patching the `pages_module` attribute, as shown, is correct).

- [ ] **Step 6: Run to verify failure**

Run: `uv run pytest <chosen module>::test_post_save_side_effects_can_be_skipped -v`
Expected: FAIL with `TypeError: ... unexpected keyword argument 'sync_media'` (Wagtail's `Page.save` rejects unknown kwargs).

- [ ] **Step 7: Add the opt-out keywords to `Post.save`**

Replace:

```python
    def save(self, *args, **kwargs) -> None:
        save_return = super().save(*args, **kwargs)
        self.sync_media_ids()
        create_missing_renditions_for_posts(iter([self]))  # needed for images src / srcset
        return save_return
```

with:

```python
    def save(self, *args, **kwargs) -> None:
        sync_media = kwargs.pop("sync_media", True)
        create_renditions = kwargs.pop("create_renditions", True)
        save_return = super().save(*args, **kwargs)
        if sync_media:
            self.sync_media_ids()
        if create_renditions:
            create_missing_renditions_for_posts(iter([self]))  # needed for images src / srcset
        return save_return
```

- [ ] **Step 8: Run the opt-out test and the model suites**

Run: `uv run pytest <chosen module> tests/models_test.py -q`
Expected: PASS. Then `uv run ruff check src/cast/models/video.py src/cast/models/pages.py && uv run mypy` — clean.

---

### Task 4: Documentation, release notes, and backlog bookkeeping

**Files:**
- Modify: `docs/releases/0.2.62.rst`, `BACKLOG.md` (the "Model-layer decoupling" item), `backlog/2026-07-02-architecture-review.md` (M1/H1/H2 fix notes)

Handled by the orchestrating session, not a subagent: add release-note bullets for the stateless `get_description` fix (user-visible: repeated renders of one instance no longer leak the feed template), the atomic `Video.save`, and the new `Post.save` opt-out keywords; annotate M1 as fixed and H1/H2 as partially fixed (phase 1) in the review doc; update the backlog item to phase-2 scope only.

---

## Verification (after all tasks)

1. `just check` — lint, mypy, full suite, 100% branch coverage.
2. `python3 ~/projects/agent-stuff/claude/skills/pi-review-loop/bin/pi-review-loop --repo "$PWD" --run-dir "$(mktemp -d)/pi-review"` — repeat fix/re-review up to 3 rounds until CLEAN.
3. Sibling-repo check: `HtmxHttpRequest` stays importable from `cast.views`; no template/context/URL contracts changed; new save kwargs are additive — no sibling changes expected, confirm nothing greps for `_local_template_name` in `../cast-bootstrap5`, `../cast-vue`, `../homepage`, `../python-podcast`.
