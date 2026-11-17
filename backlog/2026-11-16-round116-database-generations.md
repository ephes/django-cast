# Round 116: database and file generations

Implemented on `codex-q/r116-django-cast`, based on fresh `origin/develop`
`93ac6cb4` (the release/default branch is `main`). All four scout scopes were
still applicable after the round 114 integration.

- B20: repository subtype/content-type, contributor/avatar and visibility queries
  follow the source alias. Feed/index and navigation querysets retain that alias.
  Serialized projections hydrate with Django `from_db()` and preserve database
  state through media, sites, renditions and nested contributor/season/artwork data.
  Bound sites from another source database are refused before data assembly.
- B21: glossary file reads fence descriptor identity, size, nanosecond modification
  and change metadata and consumed length. An unlink-only change during atomic
  pathname replacement retains the coherent old descriptor. Symlinks remain valid.
  Podcast application binds episode/transcript selection to the selected database
  and preflights podcast and actual transcript routing before artifact access.

Focused synthetic regressions failed before each fix: S44 four failures, S45
eight failures, S46 six failures, S47 eight failures. Two independent disposable
aliases contain colliding page, audio, transcript and contributor IDs; default
queries are rejected during selected-source operations. Additional tests cover
cold/JSON cache reconstruction, visibility, lazy related access, dry runs,
restored modification times, truncation, short reads, symlinks and atomic replacement.

The existing unreleased `docs/releases/0.2.68.rst` contains the release notes per
AGENTS policy; no version was changed. `BACKLOG.md` had no outstanding implementation
item for these scopes. No workflow or integration branch was changed.

Read-only consumer checks: `~/projects/cast-bootstrap5`, `~/projects/homepage`
and `~/projects/python-podcast`. Existing template/context contracts are retained;
both sites configure the default database. No consumer change was identified.
`cast-vue` was inspected in the retained read-only clone
`~/workspaces/ws-cx-scout112/cast-vue`; its contributor/page context usage is compatible. Built-in concrete image support is unchanged.
Wagtail's global URL registry/site discovery remains the consuming site's routing
responsibility; the repository accepts the matching source request/site.

## Local gate results

Passed with workspace-local `UV_TOOL_DIR` and `UV_CACHE_DIR` as shown below:

```sh
UV_TOOL_DIR=/Users/jochen/workspaces/ws-cx-cx-r116-django-cast/.cache/uv-tools UV_CACHE_DIR=/Users/jochen/workspaces/ws-cx-cx-r116-django-cast/.cache/uv just check
UV_TOOL_DIR=/Users/jochen/workspaces/ws-cx-cx-r116-django-cast/.cache/uv-tools UV_CACHE_DIR=/Users/jochen/workspaces/ws-cx-cx-r116-django-cast/.cache/uv just check-compatibility
UV_TOOL_DIR=/Users/jochen/workspaces/ws-cx-cx-r116-django-cast/.cache/uv-tools UV_CACHE_DIR=/Users/jochen/workspaces/ws-cx-cx-r116-django-cast/.cache/uv just check-python
```

- Full gate: lint, types, isolated collection, 5,547 Python tests passed / 44
  backend/opt-in skips, 100% statement and branch coverage; 226 JavaScript tests,
  TypeScript, asset builds/freshness, npm audit, Sphinx and dependency/floor audits.
- All six compatibility environments passed, plus Python 3.13/Wagtail 8.1.
  The final 40 focused regressions were rerun successfully in all seven installed
  tox environments after the last site-affinity guard, using their Python
  interpreters and the same isolated database/media settings.
- The docs build retains the pre-existing nonfatal heading-style warning at
  `docs/development.rst:891`. No warning originated in the edited docs.
- Audits found no known vulnerabilities. Their initial successful run warned
  about an unwritable system HTTP cache; equivalent runtime and advisory-floor
  audits were then rerun with pip-audit's public
  `--cache-dir /Users/jochen/workspaces/ws-cx-cx-r116-django-cast/.cache/pip-audit`.
- `git diff --check` passed. No owner decision is required for these fixes.

## External PostgreSQL acceptance

The complete gate command (workspace-local uv tools/cache):

```sh
UV_TOOL_DIR=/Users/jochen/workspaces/ws-cx-cx-r116-django-cast/.cache/uv-tools UV_CACHE_DIR=/Users/jochen/workspaces/ws-cx-cx-r116-django-cast/.cache/uv just check-postgres
```

Both PostgreSQL tox environments cannot connect to `127.0.0.1:5432` (connection
refused). Starting an owned disposable cluster was also blocked by the sandbox:

```sh
initdb -D /Users/jochen/workspaces/ws-cx-cx-r116-django-cast/.cache/postgres-r116 -A trust -U postgres
```

PostgreSQL reports `could not create shared memory segment: Operation not permitted`
from `shmget`. The external clerk must rerun `just check-postgres` with a disposable
PostgreSQL service, then run the new two-alias regressions against it as well:

```sh
CAST_TEST_DB_ENGINE=django.db.backends.postgresql CAST_TEST_DB=cast_r116_tests CAST_TEST_DB_USER=postgres CAST_TEST_DB_PASSWORD=postgres uv run --with 'psycopg[binary]>=3.3,<4' pytest -q tests/repository/database_test.py tests/glossary_apply_database_test.py tests/glossary_generation_test.py
```

The secondary alias is intentionally an independent in-memory SQLite database in
`tests.settings`; the PostgreSQL command exercises the default alias on PostgreSQL
and preserves that independent collision oracle.

Logs are outside the clone in
`/Users/jochen/workspaces/ws-work-planning/coordination/codex/logs/cx-r116-django-cast/`.
The external clerk performs the cross-family review and merge. No worker review
CLI, push, PR, merge, deployment or host access was used.

## Integration acceptance (2026-11-17)

`just check-postgres` passed against a disposable PostgreSQL 17 container, and the
three two-alias regression files above passed on PostgreSQL and SQLite. The fixture
now pins the colliding podcast/episode page IDs, because PostgreSQL sequences do
not follow explicit inserts. Integration review also bound the
`CAST_REPOSITORY = "django"` feed path and the `Blog.last_build_date` fallback to
the blog database, and re-resolves replica-routed sites on the source database
instead of refusing them.
