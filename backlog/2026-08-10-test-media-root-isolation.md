# Isolate test media roots so concurrent test runs don't clobber each other

Status: IMPLEMENTED in 0.2.64.

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

## Implementation

`tests/settings.py` accepts `CAST_TEST_MEDIA_ROOT` and
`CAST_TEST_PRIVATE_MEDIA_ROOT` overrides while retaining the existing local defaults.
Every tox environment sets both paths from its environment name, and the cleanup
environment removes their directories. No media fixtures are stored under the default
roots; the suite creates its files during each run. The default `just tox` recipe can
therefore run six tox environments concurrently without cross-session media deletion.

Local plain `pytest` runs still share the default path. Two simultaneous plain pytest
runs can therefore conflict, but tox-vs-pytest and environment-vs-environment runs are
isolated, covering the normal parallel-matrix and agent-vs-terminal workflows.
