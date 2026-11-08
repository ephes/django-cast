# Scout round 83: publication and acceptance outcomes

Implemented bundle B23 against develop. All three reported paths remained
unfixed at the inspected trunk. Equal-date index/feed queries now share a
stable descending primary-key tie-breaker, default backup and restore propagate
per-path failures while completing independent copies, and Ajax comments record
required ownership transactionally before robust post-commit observers.

Synthetic regressions cover both repository modes, RSS/Atom and podcast/blog
feeds, ascending/descending index pages, backup/refresh/restore failures, observer
exceptions, outer commit/rollback and required ownership failure. Each bug
regression fails against the pre-fix source. No templates, context keys, feed
URLs, schema or dependencies changed. Consumer backup automation must now handle
nonzero exits for partial failure; no consumer source changes are needed.

## Resume note: parked for Claude finisher

Branch: `fix/scout83-publication-outcomes`, based on `6c5d6b83` from
`origin/develop`. All three scout slices are implemented, none merged:

1. `cast-index-equal-date-stable-pagination`
2. `cast-media-sync-command-partial-failure-exit`
3. `cast-comment-observer-failure-acceptance-contract`

Required Opus review could not run. The installed claude-review-loop harness
with `--model claude-opus-5-5 --effort high` returned `PROVIDER_ERROR` / `api_error`:
"OAuth session expired and could not be refreshed". No review verdict exists.
Restore Claude authentication, then run a fresh whole-bundle review, fixing and
re-reviewing required findings under the owner's four-round/recurrence rules.
The original attempt had no skipped files, truncations or redactions.

Local PostgreSQL is also blocked: Homebrew PostgreSQL 17 `initdb` fails at
`shmget` with "Operation not permitted", including with mmap options. No local
server answers on 127.0.0.1:5432. SQLite outer-transaction commit/rollback journeys
run without platform skips, but the required PostgreSQL transaction gate remains
unverified. Run those tests and the existing PostgreSQL lock journeys in a
permitted local environment. Do not use GitHub Actions as a substitute.

Before merging, fetch origin, rebase onto current `origin/develop`, rerun
`UV_CACHE_DIR=<workspace>/.cache/uv just check` (100% coverage required) and
`uv run sphinx-build -n -W --keep-going -b html docs docs/_build/html`.
Review committed changes against develop (the review harness normally bundles
uncommitted changes; use a review worktree with the bundle diff applied).
Only after a clean or suggestion-only review and required checks, merge locally
with `--no-ff` into develop, rerun full local checks, push develop and verify
with `git ls-remote`. Never push main. No PRs, deploys, releases, tags, remote
branch deletion or Actions. The parking commit uses `[skip ci]`.

## Final local validation

- `just check`: passed on Python 3.15.2, Django 6.1.3, Wagtail 8.1:
  Ruff lint/format, mypy (179 files), 4,505 tests passed, 23 existing backend
  skips, 100% Python line and branch coverage.
- Strict Sphinx HTML: passed with `-n -W --keep-going`.
- Final regression proof on unchanged develop: 22 failed, 1 passed; the passing
  case preserves already-working refresh-mode error handling. Feed regressions
  use synthetic enclosure metadata with no audio files or probes.
- `git diff --check`: passed. JavaScript unchanged; no rebuild needed.
- Review: unavailable due expired OAuth, not a clean verdict. PostgreSQL
  validation remains blocked as described above. No merge or trunk push.
