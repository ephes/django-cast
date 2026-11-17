# Round 126: rendition transaction and cache boundaries

Implemented B11 in slice order: `sync-renditions-unwinds-rolled-back-storage-writes`
then `rendition-repair-invalidates-cache-after-commit`.

The command carries a per-image receipt through repair and creation. Both use
Wagtail's public generator and Django's file/model APIs with fresh names. An
exact acknowledged key is compensable after rollback when no row references
it; changed backend names are retained with a warning. Verification reads the
writer's rows. A concurrent unique-key conflict safely fails the attempt; retry
reuses the committed winner. Earlier image commits remain valid.

Repair cache callbacks bind to the saved rendition's database alias and run at
the outer commit. Rollback drops callbacks. A callback error explicitly reports
committed/cache-pending state and recovery identifiers; it never triggers
compensation of committed output. Only `sync_renditions` opts into the raising
mode (`strict_cache_invalidation=True`); there, retry all cache purges for that
image because Django stops later callbacks after an exception. Embedded callers
(publication signal, galleries, style guide) log the same identifiers at ERROR
and keep later commit callbacks running. See the maintenance contract in
`docs/reference/management-commands.rst`.

Regression evidence: focused rollback tests fail on the original command;
commit/rollback/alias and cache-outage tests fail before after-commit scheduling.
The PostgreSQL two-connection test deliberately refills the old row while repair
is uncommitted and checks public cache reads after commit. It is included in
both `just check-postgres` lanes. SQLite skips only that concurrency oracle.

Consumer inspection: homepage has its own independent repair command and cache
retry option; python-podcast has no direct call of the changed helpers. No
consumer source or media was modified. Existing helper signatures and command
selectors remain compatible. No schema or version changes.

## Local validation and remaining acceptance

- `just check` passed: 5,574 Python tests passed, 47 configured skips,
  100% line/branch coverage; lint, mypy, isolated test collection, TypeScript,
  265 JavaScript tests, rebuilt-asset comparison, Sphinx and both dependency
  audits passed. `UV_TOOL_DIR`, `UV_CACHE_DIR` and `XDG_CACHE_HOME` pointed into
  the worker workspace's `.cache` for sandbox-compatible tool caches.
- `just check-postgres` was attempted for both configured lanes. Neither can
  connect to a local server at `127.0.0.1:5432`. Disposable bootstrap with
  `initdb -D /Users/jochen/workspaces/ws-cx-cx-r126-django-cast/.cache/postgres-r126 -A trust -U postgres`
  was also attempted and blocked by `shmget: Operation not permitted`.
  PostgreSQL qualification, including the new independent-connection cache
  barrier, was left to the merge clerk.
- Merge qualification (2026-11-17): `just check-postgres` passed both lanes
  (`postgres`, `postgres-wagtail81`) against a disposable PostgreSQL 17 cluster,
  including the cache refill barrier and rollback tests (not skipped).
- Pre-fix regression receipts and full gate output are retained outside the
  clone under the coordinator's `logs/cx-r126-django-cast/` directory.
