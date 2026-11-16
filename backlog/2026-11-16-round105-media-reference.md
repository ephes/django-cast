# Media chooser and reference-site recovery

Implementation handoff for scout round 105 bundles B13 and B14. Base:
`develop` at `6f54b3f358502e696800ab7646f9f6db3b282334`.
All six findings still applied; none required an owner decision. Work is parked on
`codex-q/r105-django-cast` for the external Claude clerk to review and merge. No reviewer, merge, Actions,
release, deployment or work-app write was run by this worker.

## Implemented

- `video-chooser-chosen-value-render-contract`: use Wagtail's chooser renderer
  directly for Audio and Video, eliminating scalar re-wrapping and duplicate HTML.
- `media-chooser-edit-destination-key-contract`: use `edit_url` in widget,
  telepath, modal responses and scripts; support Wagtail's Edit-link selector.
- `media-chooser-deleted-selection-recovery`: only model `DoesNotExist` becomes
  an empty chooser. Invalid IDs and database failures still propagate.
- `reference-site-reset-owned-subtree-boundary`: admit the expected seed-owned
  root types directly below the selected Site; delete only those subtrees.
  Refuse duplicate, wrong-type, ownerless or differently owned roots. Seed lookup
  and output counts are scoped to the same tree.
- `reference-site-reset-rebuild-transaction`: prepare media before deletion,
  reuse those assets for the rebuild, and include deletion, page creation and
  context preparation in one database transaction. Storage writes can remain
  after failure and are not claimed to roll back.
- `reference-command-option-state-restoration`: temporary setting overrides
  restore configured or absent values on success and failure.

Documentation and the current unreleased `docs/releases/0.2.68.rst` match the
changes. No version bump. Read-only theme/consumer inspection found no required
sibling changes; `cast-vue` was not present locally.

## Regression evidence

Before fixes, the six rendering/state/stale-selection cases in
`tests/widget_test.py` failed; afterward all twelve widget tests passed.
Against the original command and styleguide implementation, all ten targeted
reset boundary, rollback/preflight and option isolation cases failed. The
corrected fixtures bypass sibling slug validation only to simulate ambiguous
legacy data. The initial combined focused run passed 104 tests; subsequent
coverage runs also include empty-site and ownerless-root cases. The final reference
command module passes all 21 tests. Two sharpened boundary/builder tests also fail
against an isolated archive of the original source (2 failed, 19 deselected).

Rollback tests compare original Page and Post rows after failures following the
first real deletion, after new post creation, in context preparation and during
media preflight. All fixtures and media are synthetic; no configured remote
media backend was contacted.

## Qualification and blocked follow-up

Logs: `/Users/jochen/workspaces/ws-work-planning/coordination/codex/logs/cx-r105-django-cast/`.

`just check` passes: Ruff, mypy (183 files), isolated collection (5,398 tests),
Python tests (5,405 passed, 44 skipped), 100% statement/branch coverage (18,526
statements, 5,738 branches), JavaScript typecheck and 226 tests, reproducible
frontend builds, zero-vulnerability npm audit, docs and both Python audits.
The docs build succeeds with one warning counted; the newly introduced heading
underline warning was corrected. Initial uv tool-directory creation was blocked;
the complete successful invocation uses:

```sh
UV_TOOL_DIR=/Users/jochen/workspaces/ws-cx-cx-r105-django-cast/.cache/uv-tools \
PIP_CACHE_DIR=/Users/jochen/workspaces/ws-cx-cx-r105-django-cast/.cache/pip-audit \
just check
```

`pip-audit` does not use `PIP_CACHE_DIR` for its own advisory cache. The runtime
and all advisory-floor audits were additionally run with an explicit
`--cache-dir /Users/jochen/workspaces/ws-cx-cx-r105-django-cast/.cache/pip-audit`;
all report no known vulnerabilities, with no cache-write warning.

Python 3.13/Django 6.1/Wagtail 8.1 passes (5,357 tests and the separate 91-test v3
experiment; PostgreSQL and optional browser skips are expected). The compatibility
matrix also passes all six configured environments: Python 3.11/Django 5.2 with
Wagtail 7.0 and 8.1; Python 3.12/Django 6.0 with Wagtail 7 latest; Python 3.14 and
3.15/Django 6.1 with Wagtail 8.0; Python 3.14/Django 6.1 with Wagtail 8.1. All
configured v3 experiment runs pass as well. The matrix and Python 3.13 gate use
the same `UV_TOOL_DIR` override:

```sh
UV_TOOL_DIR=/Users/jochen/workspaces/ws-cx-cx-r105-django-cast/.cache/uv-tools just check-compatibility
UV_TOOL_DIR=/Users/jochen/workspaces/ws-cx-cx-r105-django-cast/.cache/uv-tools just check-python
```

PostgreSQL qualification remains blocked. Exact attempted commands:

```sh
initdb -D /Users/jochen/workspaces/ws-cx-cx-r105-django-cast/.cache/pgdata -A trust
UV_TOOL_DIR=/Users/jochen/workspaces/ws-cx-cx-r105-django-cast/.cache/uv-tools just check-postgres
```

`initdb` fails at `shmget` with `No space left on device` (shared memory);
both tox PostgreSQL environments then fail setup with connection refused at
`127.0.0.1:5432`. With a local PostgreSQL service, also run the focused widget and
reference-command tests against PostgreSQL using `tests.settings` and
`CAST_TEST_DB_ENGINE=django.db.backends.postgresql`.

The existing opt-in browser gates were attempted with:

```sh
CAST_RUN_BROWSER=1 \
CAST_TEST_DB=/Users/jochen/workspaces/ws-cx-cx-r105-django-cast/.cache/browser.sqlite3 \
uv run pytest tests/transcript_admin_browser_test.py tests/comments/comment_browser_test.py -q
```

All three fail before browser interaction: Chromium cannot register its Mach
rendezvous port (`bootstrap_check_in`, permission denied). They must run outside
this sandbox. The ordinary suite skips these opt-in journeys deliberately.
