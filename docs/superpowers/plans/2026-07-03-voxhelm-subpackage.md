# Voxhelm subpackage extraction (architecture review M3, 2026-07-03)

Backlog item: "Voxhelm optional subpackage" — split `voxhelm.py` into a `voxhelm/` subpackage, break the
models↔voxhelm circular imports, fold the site→setting→env chain into the subpackage's settings module
(M2 remainder), and record the optional-extra decision.

Roles: pi (gpt-5.5) implements per task briefs; claude reviews every diff and runs the gates.
Branch: develop, working-tree only — commit only after all gates pass ("# "-prefixed messages).

## Binding scope decisions

1. **Package layout** — `src/cast/voxhelm/` with:
   - `exceptions.py`: `VoxhelmError`
   - `settings.py`: the site→setting→env precedence chain (`get_setting`, `require_setting`,
     `get_float_setting`, `get_bool_setting`, `get_site_setting_value`, `SITE_SETTING_FIELD_MAP`,
     `TRUE_SETTING_VALUES`/`FALSE_SETTING_VALUES`). This satisfies the M2 remainder: the chain is a
     deliberate third mechanism (site settings beat Django settings beat env) and stays out of
     `CAST_SETTING_REGISTRY`, but now lives in one named settings module.
   - `client.py`: HTTP transport — `VoxhelmClient`, `open_url`, `read_response_bytes`,
     `read_http_error_detail`, `normalize_api_base`, `NoRedirectHandler`, size constants,
     `TERMINAL_JOB_STATES`, `KNOWN_SPEAKER_STRATEGY`
   - `task_refs.py`: the pure task-ref string helpers
   - `service.py`: domain orchestration — dataclasses, artifact path/validation helpers, known-speaker
     payload builders, diarization resolvers, `VoxhelmTranscriptService`,
     `enqueue_audio_transcript_generation`
   - `__init__.py`: re-exports the full previous `cast.voxhelm` public surface (incl. `Transcript`,
     `TranscriptGeneration`, which tests reference as `cast.voxhelm.Transcript`)

2. **Cycle break** — the cycle was `models/__init__` → `models/pages` → `wagtail_panels` →
   (function-body) `voxhelm` → `models`. Fix: `get_transcript_generation`,
   `get_transcript_generation_status_context`, and `transcript_complete` move to
   `cast/transcripts/generation_status.py` (they are transcript-generation presentation/domain logic, not
   Voxhelm integration; they need only the `cast.models.transcript_generation` leaf module).
   `wagtail_panels.py` imports it at module level — no function-body import. `cast.voxhelm` re-exports
   the three names for compatibility. Invariant, pinned by a subprocess test: `django.setup()` (which
   imports `cast.models`) must not import `cast.voxhelm`.

3. **`voxhelm_tasks.py` stays at `src/cast/voxhelm_tasks.py`** — unchanged file, unchanged module path.
   Reasons: (a) django-tasks stores the task path in DB rows, moving it would strand queued work across
   an upgrade; (b) `@task(backend="cast_transcripts")` fails **at import time** when the `cast_transcripts`
   TASKS backend is not configured (verified empirically 2026-07-03: `InvalidTaskBackendError` on module
   import). The function-body import of `complete_transcript_generation` inside
   `enqueue_audio_transcript_generation` is therefore the load-bearing optionality seam — installs that
   never enqueue never need the TASKS backend — and is retained with a comment stating that constraint.
   It is not papering over the models cycle (which is gone).

4. **Optional-extra decision (recorded)** — no `[voxhelm]` packaging extra. `django-tasks` stays a hard
   install dependency: it is lightweight (Django + typing-extensions), and making it optional would turn a
   clean `ImproperlyConfigured`/no-op posture into ImportError crashes in half-configured installs. The
   optionality that matters is behavioral and already/now exists: models and migrations are unconditional
   (Django model discovery cannot be optional), the TASKS backend is only required at first enqueue (see
   3), and the admin wiring (action menu item, audio edit button, POST endpoints) is gated on the Voxhelm
   configuration being resolvable for the request's site (task 2). The existing optional extra keeps
   carrying `django-tasks-db` for the worker.

5. **Behavior preservation (task 1)** — the split is byte-faithful: moved bodies identical modulo import
   changes. Test changes limited to patch-target repoints onto the module where the name is *used*
   (`cast.voxhelm.client.open_url`, `cast.voxhelm.service.resolve_audio_source_url`, …); class-attribute
   patches (`VoxhelmTranscriptService.submit_for_audio`, `Transcript.objects.get_or_create`) stay.

6. **Configuration gate (task 2)** — `user_can_generate_transcript_for_audio` is the single choke point
   (episode action menu item, audio edit button, and both POST endpoints all route through it). It gains a
   configured-check: `CAST_VOXHELM_API_BASE` and `CAST_VOXHELM_API_KEY` must resolve non-empty through the
   settings chain for the request. Existing permission tests get explicit Voxhelm configuration; new tests
   pin the unconfigured-hidden behavior (env fallback cleared via monkeypatch.delenv).

## Tasks

- Task 1 (pi): subpackage split + cycle break + test repoints — `.superpowers/sdd/m3-task1-brief.md`
- Task 2 (pi): configuration-gated admin wiring — `.superpowers/sdd/m3-task2-brief.md`
- Task 3 (controller): decision recording, release notes, review-doc fix note, BACKLOG removal, ledger,
  commit

Gates per task: full pytest, ruff, mypy, 100% branch coverage (`just check`); claude reviews each diff.
