# Round 110: transcript consent and glossary imports

Status: implemented locally; external browser/PostgreSQL acceptance pending.

The three slices run in order from `develop` (`939e6d7e`):

- `transcript-regeneration-confirmation-generation`: signed transcript/review,
  immutable audio-source and attempt evidence, compared under enqueue write locks;
  stale consent returns HTTP 409 before submission. Completion fences remain in place.
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

The merge clerk must run these outside the worker sandbox:

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
but its Mach-port `bootstrap_check_in` is refused by the sandbox. These are
uncompleted environment-dependent acceptance checks, not passing tests.
The two-alias rollback fixtures run in the regular Python suite; the existing
PostgreSQL glossary concurrency fixtures remain in `just check-postgres`.

No owner decision is required. Everything remains on the local
`codex-q/r110-django-cast` branch for clerk review; nothing is pushed or merged.
