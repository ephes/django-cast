# Upstream the modelsearch Django 6.1 MATCH fix, then remove the shim

Status: IMPLEMENTED (2026-09-19) — modelsearch 1.3.2 is now required and the local shim is removed.
Retained as historical context.

## Background

Django 6.1 restructured `DatabaseOperations.conditional_expression_supported_in_where_clause`:
on backends without a native boolean field (SQLite), only `Exists`, `Lookup`, and `WhereNode`
conditions compile bare — every other boolean-output expression is wrapped in `= True`.

`modelsearch` (the package Wagtail ≥ 7.1 delegates search to; ≤ 1.3.1 affected) filters its
SQLite FTS index with a plain-`Expression` subclass `MatchExpression`
(`modelsearch/backends/database/sqlite/query.py`), used at a single call site in
`modelsearch/backends/database/sqlite/sqlite.py`
(`SQLiteFTSIndexEntry.objects.filter(match_expression)`). Under Django 6.1 the generated SQL
becomes `<fts_table> MATCH ? = ?`, which SQLite rejects with
`OperationalError: unable to use function MATCH in the requested context`. Before the
workaround this broke every SQLite full-text search (29 test failures).

## Former workaround in django-cast

`src/cast/modelsearch_compat.py` (added in 0.2.64, commit `a66a82a7`) wrapped the match
expression in a `Lookup` subclass so Django compiled it bare and emitted identical
SQL. It was applied from `CastConfig.ready()` when `django.VERSION >= (6, 1)`,
was idempotent, and tolerated `modelsearch` being absent (Wagtail 7.0). Its tests
lived in `tests/modelsearch_compat_test.py`.

## Resolution

Upstream [issue #104](https://github.com/wagtail/django-modelsearch/issues/104)
was fixed by [PR #105](https://github.com/wagtail/django-modelsearch/pull/105),
which makes `MatchExpression` a `Lookup` subclass. The fix shipped in
[modelsearch 1.3.2](https://github.com/wagtail/django-modelsearch/releases/tag/v1.3.2).
No duplicate report is needed.

django-cast now requires `modelsearch>=1.3.2,<1.4` (the lockfile already resolved
1.3.2). The shim, its startup hook and implementation-specific tests are removed;
the existing functional search regressions remain. Consumer sites homepage and
python-podcast accept this dependency range, so no sibling changes are required.

The initial cleanup exposed a supported-matrix conflict in CI: Wagtail 7.3.4
requires modelsearch below 1.3. After explicitly approving the support change,
the maintainer chose to exclude all Wagtail 7.3 releases rather than restore the
shim. Upstream security support for 7.3 ended on 25 August 2026
([release schedule](https://github.com/wagtail/wagtail/wiki/Release-schedule)).
Installation guidance directs affected sites to 7.4 LTS. Wagtail 7.0 LTS remains
supported; both known consumer sites already require Wagtail 8.0.
