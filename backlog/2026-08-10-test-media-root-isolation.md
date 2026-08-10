# Isolate test media roots so concurrent test runs don't clobber each other

Status: OPEN — known wart, fix not yet commissioned.

## Background

`tests/settings.py` pins `MEDIA_ROOT = tests/media` and
`CAST_PRIVATE_MEDIA_ROOT = tests/private-media` as absolute paths derived from the
checkout, and `tests/conftest.py` has a session-scoped autouse fixture
(`remove_stale_media_files`) that `shutil.rmtree`s both roots at session start and end.

tox gives every environment its own *database* file
(`CAST_TEST_DB={toxworkdir}/{envname}-test_database.sqlite3`) but does **not** isolate
the media roots. Two test sessions running concurrently in the same checkout — e.g.
`time tox` in a terminal while another agent/session runs `pytest` — therefore delete
each other's uploaded media mid-run.

Observed symptom (2026-08-10): exactly 7 failures, all
`ffprobe ... returned non-zero exit status 1` on `tests/media/cast_audio/test.m4a`,
in an otherwise fully green run. If unexplained ffprobe/media failures appear, suspect
a concurrent run before suspecting the code.

## Proposed fix

Follow the `CAST_TEST_DB` pattern:

1. Introduce `CAST_TEST_MEDIA_ROOT` / `CAST_TEST_PRIVATE_MEDIA_ROOT` env overrides in
   `tests/settings.py` (defaults unchanged: `tests/media`, `tests/private-media`).
2. Set them per environment in `tox.ini` (`{toxworkdir}/{envname}-media` etc.), and add
   the new directories to the `cleanup` env (glob expansion via python — tox runs
   commands without a shell).
3. Alternatively (stronger): derive per-session roots via `tmp_path_factory` in
   conftest and drop the rmtree fixture entirely — but check first which tests rely on
   fixture files pre-seeded under `tests/media` versus files created during the run.

Local plain `pytest` runs would still share the default path; that is acceptable — the
realistic collision is tox-vs-pytest or agent-vs-terminal, which per-env tox roots solve.
