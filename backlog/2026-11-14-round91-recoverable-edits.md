# Round 91 B30: recoverable media and comment edits

Implemented on `codex-q/r91-django-cast`, based on fresh `origin/develop` at `37a86323963ec2684ddcf2e0b821a927e1013729`.
No version bump, merge, release, host access, Actions reliance or review-agent invocation.
The external Claude clerk owns cross-family review and integration.

## Scope, in order

- `cast-ingest-interruption-compensation`: compensate create/replacement writes
  on KeyboardInterrupt/SystemExit, attempt remaining cleanup, log exact recovery
  storage keys on failed removal, and re-raise the original interruption. A
  post-commit callback interruption must retain committed files.
- `cast-refresh-failed-final-write-recovery-copy`: verify stage/source digests,
  retain the complete reserved recovery key on final publication failure, report
  it and exclude it from synchronization. Unverified/incomplete stages are removed.
  Generic Storage final writes remain non-atomic; explicit recovery and cleanup
  are documented in the management-command reference.
- `cast-comment-edit-stale-text-conflict`: require a content token, compare under
  the existing row lock before moderation/save, return 409/current text on conflict,
  preserve the browser draft and require explicit review/retry. No model migration.

## Regression evidence

Old-code failures are saved outside the checkout in the worker log directory:
`73-red.log`: eight real-file create/replacement interruption failures;
`72-red.log`: complete stage missing after partial final write/source removal;
`74-red.log`: stale editor incorrectly received 200;
`74-js-red.log`: revision forwarding/refresh and conflict preservation failed.
Synthetic files, text and accounts only. Real FileSystemStorage partial writes
are tested separately from storage doubles. PostgreSQL locks and Chromium UI
remain separate acceptance gates, never inferred from SQLite/jsdom results.

## Compatibility inspection

- Bootstrap5 `f72c844a9468`: post template loads the shared comments bundle;
  it does not replace the core raw-text/edit controls.
- Vue `b82a2e62f142`: separate Vue comment-posting integration, no core inline
  author edit form or management-command wrapper.
- Read existing workspace homepage/python-podcast consumers: no custom raw-text
  or edit-action override; deployment docs describe media refresh behavior but
  no scheduled job invokes it. No required setting, schema or CLI option changes.
  The Python Podcast staging UI probe uses the retained shared selectors.
- Custom third-party clients must adopt the revision token. Legacy open pages
  receive 409 and retain drafts until refreshed. Content tokens deliberately
  admit an intervening edit that restores exactly the original text.

## Local validation

Final local results: `just check` passed (Ruff, mypy: 179 source files,
4,736 Python tests passed / 37 skipped, statement and branch coverage 100%).
All 219 JavaScript tests passed; JS typecheck, shipped comment/Vite builds and
`just verify-assets` passed. Strict Sphinx and Django system/migration checks
passed. Chromium and PostgreSQL remain blocked as detailed below.
See the final worker report for the pushed commit SHA. Logs are under
`/Users/jochen/workspaces/ws-work-planning/coordination/codex/logs/cx-r91-django-cast/`.
Full gates: `CAST_TEST_DB=tests/r91-check.sqlite3 just check`, `just js-typecheck`,
`just js-test`, `just js-build-comments`, strict Sphinx, Django system check and
`makemigrations --check --dry-run`. Python system commands need `PYTHONPATH=.`.
The initial full suite was invalidated by a concurrently launched browser test
using the same SQLite file; final runs use independent database files.

Blocked PostgreSQL bootstrap (no race result):

```sh
/opt/homebrew/opt/postgresql@17/bin/initdb -D /private/tmp/cast-r91-pg -A trust
```

Sandbox rejects `shmget`: `could not create shared memory segment: Operation not permitted`.
Outside the sandbox, start a disposable PostgreSQL and run with its connection
settings: `uv run --with 'psycopg[binary]' pytest tests/comment_database_races_test.py tests/replacement_ownership_test.py` (set `CAST_TEST_DB_ENGINE=django.db.backends.postgresql`
and disposable `CAST_TEST_DB`, host/port/user/password as documented).

Blocked browser journey, with workspace-local installed Chromium:

```sh
PLAYWRIGHT_BROWSERS_PATH=/Users/jochen/workspaces/ws-cx-cx-r91-django-cast/.cache/ms-playwright CAST_TEST_DB=tests/r91-browser.sqlite3 CAST_RUN_BROWSER=1 uv run pytest tests/comment_browser_test.py -q
```

Chromium is terminated at `bootstrap_check_in … MachPortRendezvousServer` with
`Permission denied (1100)`. Browser code cannot reach the page journey in this
sandbox. Re-run the exact opt-in test outside it; it drives two open editors
against the actual Django HTTP edit route and shipped bundle.

No owner decision is needed; the external clerk must complete browser/PostgreSQL
acceptance and review before merging. Do not merge this parked branch automatically.
