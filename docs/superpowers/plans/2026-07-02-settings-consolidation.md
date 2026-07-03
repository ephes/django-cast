# Settings Consolidation Implementation Plan (M2/M12)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** One registry in `cast/appsettings.py` owns every static `CAST_*` default, the
`check_cast_setting_types` system check derives from it instead of a hand-maintained parallel table, the
scattered inline `getattr(settings, "CAST_...", default)` call sites read through the accessor, and every
user-facing setting is documented in `docs/reference/settings.rst` (findings M2 and M12 in
`backlog/2026-07-02-architecture-review.md`).

**Scope decisions (controller, 2026-07-02 — do not re-debate):**

- **Call-time semantics are the contract.** Inline `getattr(settings, ...)` reads happen at call time, so
  `@override_settings` and runtime settings changes work. Converted call sites therefore use module-attribute
  access (`appsettings.CAST_FOO`), never `from appsettings import CAST_FOO` (import-time snapshot). Existing
  from-imports (e.g. `views/media.py` pagination) keep their established import-time+patchable semantics.
- **Coercions stay at call sites.** `int(...)`/`float(...)`/`bool(...)`/`is True` wrappers around reads are
  behavior (string env values must keep coercing) — only the default value moves to the registry.
- **Kept mechanisms, deliberately:** `init_cast_settings`'s app-ready mutation only sets defaults for
  third-party settings (`SITE_ID`, `WAGTAIL_SITE_NAME`, `CRISPY_*`) that third-party code reads directly —
  read-time defaults cannot replace it; it stays. `comments/appsettings.py` stays as the comments accessor
  (it carries legacy `FLUENT_*` fallbacks and strict coercions), but its `CAST_COMMENTS_*` defaults register
  centrally. `dev_settings.dev_tools_enabled` keeps its deprecation-precedence chain. The Voxhelm
  site→setting→env chain is deferred to the Voxhelm subpackage item (M3) — it is a per-site DB-backed
  accessor, not a static default.
- **Check enforcement scope is unchanged** in this slice: the same 11 settings keep their type checks (now
  derived from registry metadata). Broadening enforcement to all registered settings is a possible follow-up,
  not part of a behavior-preserving slice.
- `CAST_SLUG` (named in finding M12) does not exist in the codebase — nothing to document; correct the
  finding instead.

## Tasks

### Task 1 (pi): Central registry + call-site conversion + derived checks
- Registry in `appsettings.py`: name → (default, optional check type); `__getattr__` and the
  `TYPE_CHECKING` block extended to all registered names; `checks.py` `CAST_SETTING_TYPES` derived.
- Convert the ~19 inline `getattr(settings, "CAST_*", <static default>)` call sites (checks.py audio player,
  podlove.py, private_storage.py, media_validation.py, models/theme.py, api/editor/media.py, the 11
  styleguide tunables) to `appsettings.CAST_*` attribute reads, coercions kept.
- Full suite green; `@override_settings`-based tests keep passing unchanged.

### Task 2 (pi): Document every user-facing setting (M12)
- Compute the set difference (registered/user-facing names vs `docs/reference/settings.rst`), add missing
  entries with defaults and one-paragraph descriptions (incl. `CAST_AUDIO_PLAYER`, `CAST_EDITOR_SCOPES`,
  `CAST_POST_BODY_BLOCKS`, the comment CSS-class/moderator settings, missing styleguide tunables).

### Task 3 (controller): review gates, release notes, backlog annotations, commit
- Opus review per task; `just check`; pi-review-loop until CLEAN; release notes; M2/M12 fix notes;
  BACKLOG.md item resolved (Voxhelm-chain remainder moved into the M3 item).
