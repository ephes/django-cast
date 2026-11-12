# Scout rounds 81 and 85: correction ambiguity and editor boundaries

Status: implemented and merged into develop (historical record).

## Round 81 C2: correction ambiguity

- Glossary additions resolve a contributor shorthand to exactly one credited
  contributor. An exact display-name match wins; several shorthand matches
  (for example two contributors sharing a first name) raise `GlossaryAddError`
  without touching glossary rows or files. Missing contributor rows are skipped.
- Corrections preflight DOTe and WebVTT destinations and refuse duplicate start
  times that would receive corrected text, in both real commits and dry runs,
  before any file is staged.

## Round 85 B08: editor boundaries

1. `cast-if-match-integer-admission`: strict quoted ASCII `If-Match` syntax, with
   DRF's bounded integer validator; oversized tokens return the editor HTTP 400
   envelope without revision writes.
2. `cast-audio-patch-locked-permission-recheck`: after locking and reloading the
   audio row, choose and change permissions are checked again before form,
   ingest, probe or storage work.
3. `cast-episode-transcript-read-audio-boundary`: episode transcript reads require
   choose permission on the latest draft's audio and return HTTP 404 otherwise.

## Validation

Synthetic regressions for every slice failed before the fixes. The full
`just check` gate (lint, mypy, tests with 100% coverage) passed on the rebased
branch, and the `postgres` tox environment, which now includes
`tests/api/editor_audio_permissions_test.py`, ran the separate-connection
permission cases against a disposable local PostgreSQL 17.
