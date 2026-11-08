# Round 85 B08 editor boundaries — resume

Status: implemented and locally checked; **not reviewed or merged**. Parked on
`fix/r85-editor-boundaries` because the required Claude review could not authenticate.
Base: `origin/develop` at `e7fd52470d2deb087716fe742eda92518b41eebb`, confirmed again
by fetch before parking. All three findings were still present; none was skipped.

Implemented in report order:

1. `cast-if-match-integer-admission`: preserve strict quoted ASCII syntax and
   use DRF's bounded integer validator; normalize decoding errors to the existing
   editor HTTP 400 envelope. Synthetic PATCH/publish regressions cover posts and
   episodes, 5,000-digit input, the 1,001-digit rejection and accepted boundaries.
2. `cast-audio-patch-locked-permission-recheck`: after locking/reloading the audio,
   recheck choose and change before form construction or storage work. Synthetic
   metadata/file interleavings revoke collection access or ownership and assert
   unchanged rows, tags, chapters, files and no form/ingest/probe/storage calls.
   The existing postgres tox command now includes these tests.
3. `cast-episode-transcript-read-audio-boundary`: check choose for the latest draft
   audio before GET status/configuration/transcript/reference probes. Synthetic
   stored and draft-only reference tests verify the indistinguishable HTTP 404;
   choose-only and no-audio reads retain their established behavior.

API documentation and Unreleased notes are updated. No versions, schemas,
dependencies, workflows, deployments or release artifacts changed.

## Validation evidence

- All new defect regressions failed before their source fixes: 8 header cases,
  4 metadata/file permission cases and 2 transcript cases. File probes are mocked;
  all new fixtures are synthetic and assertions are platform independent.
- Focused three modules: **34 passed, 4 skipped** (PostgreSQL-only cases).
- `UV_CACHE_DIR=../.cache/uv just check`: **passed**. Ruff, mypy (179 source files),
  **4,524 tests passed, 27 skipped**, **100% statement/branch coverage** on Python
  3.15.2, Django 6.1.3 and Wagtail 8.1. Existing checks select their usual local
  backend/optional-runtime skips; no Actions were used.
- Separate-connection PostgreSQL permission tests could not run. Local PostgreSQL
  17 initialization failed with `could not create shared memory segment:
  Operation not permitted` (`shmget`). Do not merge the audio locking slice on
  SQLite evidence alone. Do not substitute live databases or Actions.
- Required review command used `claude-review-loop --model claude-opus-5-5
  --effort high --record-baseline`. It returned exit 2, `PROVIDER_ERROR`, with
  **“Failed to authenticate: OAuth session expired and could not be refreshed.”**
  No review occurred; no verdict or findings can be inferred. No omissions,
  truncations or redactions were reported. The throwaway review copy was removed.
- Local artifacts (not committed): workspace `.cache/check-bundle.log`,
  `.cache/*-before.log` and `.cache/review-round1/result.json` / `events.jsonl`.

## Resume steps

1. Restore the owner's Claude authentication, fetch `origin`, and rebase this
   branch onto `origin/develop`. Never integrate into `main`.
2. Run `just check` again after rebasing. On a permitted local PostgreSQL instance,
   run `tests/api/editor_audio_permissions_test.py` with the repository's postgres
   settings and `-p tests.postgres_check`; require the four separate-connection
   cases to execute and pass. The existing `postgres`/`postgres-wagtail81` tox
   environments include this module. If PostgreSQL remains blocked, keep slice 2
   parked and split out independent slices 1 and 3 for integration.
3. Run the installed review harness in a fresh run directory with Opus 5.5 at high
   effort. One review may cover this bundle. For repair rounds, use its recorded
   baseline and scope to prior findings/repair deltas. Stop after four rounds or
   a recurring required finding, per the owner. An expired OAuth session means
   leave the branch parked and stop.
4. Only reviewed-clean changes with completed local gates may merge locally with
   `--no-ff` into `develop`. Fetch immediately before every merge; if origin moved,
   rebase and rerun checks. Run full local checks again after merging, then push
   only `develop` and verify its SHA with `git ls-remote`. Use `[skip ci]` commit
   subjects to honor the owner's no-Actions instruction. No PRs, releases, tags,
   deploys, branch deletions or work-app writes.
