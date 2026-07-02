# Media Admin Views Deduplication Implementation Plan (H4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract one shared, config-parametrized implementation for the near-identical audio/video/transcript
Wagtail-admin media views (`index`/`add`/`edit`/`delete`/`chooser`/`chosen`/`chooser_upload`) and fix the drifted
chooser pagination (`video.chooser_upload` hardcodes `per_page=10` instead of `CHOOSER_PAGINATION`).

**Architecture:** Finding H4 in `backlog/2026-07-02-architecture-review.md`. A new `src/cast/views/media.py`
holds a frozen config dataclass plus a views class; `views/audio.py`, `views/video.py`, and `views/transcript.py`
shrink to a config, thin URL-kwarg wrappers, and their genuinely type-specific views. Behavior-preserving:
URL names and kwarg names, template paths, template contexts (including which keys are present), modal-workflow
JSON shapes, message strings (msgids — a `de` locale exists), and permission checks all stay identical.

**Tech Stack:** Django 4.2–6, Wagtail 7, pytest (+pytest-django), ruff (line length 119), mypy (django-stubs).

## Global Constraints

- Do NOT run `git commit` at any point — all changes stay uncommitted in the working tree.
- 100% branch coverage (`just test` fails below); every branch of the new shared module needs coverage.
- Ruff and mypy stay clean; line length 119.
- TDD for the drift fix: failing pagination regression test first.
- URL modules in `src/cast/admin_urls/` are NOT modified.
- Templates are NOT modified (theme repos vendor them; contexts must stay key-for-key identical).

## Divergence Map (established by inspection, 2026-07-02)

| View | audio vs video | transcript |
|------|----------------|------------|
| `index` | identical modulo names/messages | no `-created` ordering, no `ordering`/`popular_tags` context keys, `audio__title__icontains` search, raw query_string |
| `add` | identical (video resolves form via `get_video_form()`) | identical shape; instance built without `user`; messages use `pk` not `title` |
| `edit` | shared skeleton; differ in old-file deletion, form `initial`, filesize source (`m4a` vs `original`), voxhelm extra context | completely different (action dispatcher) — stays local |
| `delete` | identical modulo names | identical modulo names, message uses `pk` |
| `chooser` | identical modulo names | no ordering, icontains search |
| `chosen` | identical modulo step name + payload fn | same |
| `chooser_upload` | identical EXCEPT video `per_page=10` (drift) | identical modulo names |

Cross-cutting: the reindex loop (`for backend in get_search_backends(): backend.add(obj)`) appears ~10 times.
Tests patch module globals (`cast.views.audio.CHOOSER_PAGINATION` etc.) — the shared module must read the
pagination globals at call time and the patch targets move to `cast.views.media.*`.

---

### Task 1: Shared `views/media.py` + migrate audio and video

**Files:**
- Create: `src/cast/views/media.py`
- Modify: `src/cast/views/audio.py`, `src/cast/views/video.py`
- Tests: `tests/audio_views_test.py`, `tests/video_views_test.py` (patch-target updates + new drift regression test)

- [ ] Failing regression test: video `chooser_upload` honors `CHOOSER_PAGINATION` (patch `cast.views.media.CHOOSER_PAGINATION` to `1`, two videos, expect one item pre-fix fails because of hardcoded 10)
- [ ] Create `MediaAdminConfig` (frozen dataclass) + `MediaAdminViews` with `index`/`add`/`edit`/`delete`/`chooser`/`chosen`/`chooser_upload` and a module-level `reindex(obj)` helper
- [ ] Rewrite `audio.py`/`video.py` as configs + wrappers; keep `delete_old_audio_files` in `audio.py` (tests import it)
- [ ] Update test patch targets (`cast.views.audio.MENU_ITEM_PAGINATION` → `cast.views.media.MENU_ITEM_PAGINATION`, etc.)
- [ ] `uv run pytest tests/audio_views_test.py tests/video_views_test.py tests/voxhelm_admin_test.py -q` green; ruff + mypy clean

### Task 2: Migrate transcript shared parts

**Files:**
- Modify: `src/cast/views/transcript.py`
- Tests: `tests/transcript_views_test.py` (patch-target updates only if needed)

- [ ] Wire `index`/`add`/`delete`/`chooser`/`chosen`/`chooser_upload` through the shared implementation (ordering `None`, icontains search callable, `pk`-based messages, no popular tags)
- [ ] Keep `edit`, the speaker-mapping/voice-reference helpers, and the podlove/podcastindex/webvtt/html transcript views untouched
- [ ] `uv run pytest tests/transcript_views_test.py -q` green; ruff + mypy clean

### Task 3: Docs, release notes, backlog, gates (controller)

- [ ] `docs/releases/0.2.62.rst` entry (dedup + pagination-drift fix note)
- [ ] Annotate H4 as fixed in `backlog/2026-07-02-architecture-review.md`; update the BACKLOG.md item
- [ ] `just check` (100% branch coverage) and pi-review-loop until CLEAN
- [ ] Sibling-repo check: no template/context/URL contract changed — confirm; no commits pushed

## Verification (after all tasks)

1. `just check` — lint, mypy, full suite, 100% branch coverage.
2. `python3 ~/projects/agent-stuff/claude/skills/pi-review-loop/bin/pi-review-loop --repo "$PWD" --run-dir "$(mktemp -d)/pi-review"` until CLEAN (max 3 rounds).
3. Response-shape spot check: chooser modal JSON (`step`, `error_label`, `tag_autocomplete_url`), context keys per type unchanged.
