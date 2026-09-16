# Isolate test media roots so concurrent test runs don't clobber each other

Status: IMPLEMENTED in 0.2.64 (tox environments) and 0.2.65 (plain pytest).

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

## Plain pytest (0.2.65)

`tests/conftest.py` no longer uses the fixed `tests/media` default. When
`CAST_TEST_MEDIA_ROOT` / `CAST_TEST_PRIVATE_MEDIA_ROOT` are unset, the session fixture
creates the roots with `tmp_path_factory.mktemp()` and enters
`override_settings(MEDIA_ROOT=..., CAST_PRIVATE_MEDIA_ROOT=...)` for the session, so every
pytest process gets a directory of its own and nothing is deleted at session start or end.
Roots that do come from the environment variables are still wiped before and after the
session, because the next run of the same tox environment reuses them.

`ContributorVoiceReference.clip` and `Transcript.speakers` needed one more step: a
`FileField` calls its callable `storage` argument while the model class is created, so both
kept the `PrivateFileSystemStorage` instance built from the import-time settings and wrote
into `tests/private-media` no matter what the session overrode (104 stale files were sitting
there). The fixture now discovers every field whose storage is a `PrivateFileSystemStorage`,
rebinds it to the session root, and restores it afterwards;
`tests/private_storage_test.py::test_private_model_field_storage_uses_the_session_private_media_root`
guards it. Fixing that also required `test_private_media_root_defaults_outside_media_root`
to set `CAST_PRIVATE_MEDIA_ROOT` through the `settings` fixture instead of an
`override_settings` decorator: the two together leak the decorated setting into later tests,
because the fixture restores the snapshot it took while the decorator was active.

Verified by running `uv run pytest tests/audio_models_test.py tests/models
tests/audio_views_test.py tests/file_replacement_test.py tests/transcripts` twice
concurrently: 364 passed in both processes.

Media is no longer the blocker for concurrent local runs; the reused test database is.
Two plain pytest runs share `tests/test_database.sqlite3` and fail with
`database is locked`, so a concurrent run needs its own `CAST_TEST_DB` (documented in
`docs/development.rst`). Making that automatic - a per-session database without losing
`--reuse-db` - is still open.
