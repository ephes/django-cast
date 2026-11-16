# Round 110: transcript consent and glossary imports

Status: done; merge review follow-up applied and PostgreSQL/browser acceptance passed
(see "Merge acceptance").

The three slices run in order from `develop` (`939e6d7e`):

- `transcript-regeneration-confirmation-generation`: signed transcript/review,
  immutable audio-source and attempt evidence, compared under enqueue write locks;
  stale consent returns HTTP 409 before submission. Completion fences remain in place.
  Merge review follow-up: the Voxhelm submission runs after the locks are released
  (failed submissions keep their FAILED generation, autocommit enqueue failures still
  reach the caller), and the reviewed attempt is claimed by one compare-and-swap right
  before submission or resumption, so a same-token replay cannot submit twice and a
  configuration error leaves the confirmation usable.
- `glossary-import-one-database-transaction`: select one write alias and refuse
  incompatible read/write routing. Parent lock, validation, inserts, conditional
  updates and dry-run/failure rollback use that alias.
- `glossary-import-linear-validation-context`: build one normalized namespace and
  transcript-language context under the parent lock. Accepted writes update the
  context; skipped candidates leave it unchanged. Standalone validation keeps the
  same rules, including common words and cross-term conflicts.

Regression proofs use synthetic fixtures: stale confirmations queued before the
fix; routed imports lacked correct lock/rollback protection; repeated validation
scanned the namespace/language per entry (four failing counting cases). A final isolated archive of the untouched base (`939e6d7e`) reproduces all 29
selected regressions: 17 consent, eight routing/rollback, four counting cases
(`regression-base.log`). The complete fixed suite passes. Positive controls cover unchanged consent, sequential
updates, skipped candidates, dry runs and independent alias rollback.

Usage stays compatible: no management-command option, setting, dependency,
schema or version change. Read-only searches of the scout clones of `homepage`
and `python-podcast` found no command/config usage requiring changes. The
Bootstrap/Vue theme clones provide no override of the regeneration confirmation.
Release notes live in `docs/releases/0.2.68.rst`, the existing unreleased release,
following AGENTS.md; no separate pending release page or version bump is needed.

## Local gates and external acceptance

Logs are outside the clone at
`/Users/jochen/workspaces/ws-work-planning/coordination/codex/logs/cx-r110-django-cast/`.
Set the writable tool directory for recipes invoking `uvx`:

```sh
export UV_TOOL_DIR=/Users/jochen/workspaces/ws-cx-cx-r110-django-cast/.cache/uv-tools
export PIP_CACHE_DIR=/Users/jochen/workspaces/ws-cx-cx-r110-django-cast/.cache/pip
just check
just check-compatibility
just check-python
```

`just check` covers Ruff, mypy, isolated test collection, full Python coverage,
JavaScript types/tests/build and asset comparison, npm audit, Sphinx, runtime
and advisory-floor dependency audits. Final `just check` passed: 5,459 Python
tests, 100% statement/branch coverage, 226 JavaScript tests, all listed checks.
The pip-audit recipes pass but their internal cache ignores `PIP_CACHE_DIR` in
`--disable-pip` mode; the same audits were also run with explicit
`--cache-dir /Users/jochen/workspaces/ws-cx-cx-r110-django-cast/.cache/pip-audit`.
The compatibility recipes run the existing
six dependency combinations plus Python 3.13; all seven environments pass on the
final implementation, including the existing Wagtail v3 experiment subruns.
No workflow was changed or used.

The worker sandbox could not run these (both passed at merge acceptance below):

```sh
just check-postgres
CAST_RUN_BROWSER=1 uv run pytest -q tests/transcript_admin_browser_test.py
```

PostgreSQL tox environments cannot connect to `127.0.0.1:5432`. An isolated
bootstrap also fails before a server exists:

```sh
initdb -D /Users/jochen/workspaces/ws-cx-cx-r110-django-cast/.cache/postgres -A trust
```

`shmget` reports that no shared-memory segment can be created. Chromium starts
but its Mach-port `bootstrap_check_in` is refused by the sandbox. Inside the
sandbox these remained environment-dependent checks, not passing tests.
The two-alias rollback fixtures run in the regular Python suite; the existing
PostgreSQL glossary concurrency fixtures remain in `just check-postgres`.

No owner decision is required.

## Merge acceptance

Outside the sandbox, with the merge-review follow-up applied: `just check`,
`just check-compatibility`, `just check-python`, `just check-postgres` (against a
disposable PostgreSQL 17 container via `CAST_TEST_DB_PORT`) and
`CAST_RUN_BROWSER=1 uv run pytest -q tests/transcript_admin_browser_test.py`
all pass. The changed consent and glossary test files also pass on PostgreSQL.
