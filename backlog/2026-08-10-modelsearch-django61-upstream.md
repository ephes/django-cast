# Upstream the modelsearch Django 6.1 MATCH fix, then remove the shim

Status: OPEN — django-cast carries a workaround; the proper fix belongs in `modelsearch`.

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

## The workaround in django-cast

`src/cast/modelsearch_compat.py` (added in 0.2.64, commit `a66a82a7`) wraps the match
expression in a `Lookup` subclass — whitelisted, so Django compiles it bare and emits
identical SQL. It is applied from `CastConfig.ready()` when `django.VERSION >= (6, 1)`,
is idempotent, and tolerates `modelsearch` being absent (Wagtail 7.0). Tests:
`tests/modelsearch_compat_test.py`.

## Remaining work

1. File the issue against `modelsearch` (github: wagtail org) with the analysis above;
   the shim's `MatchCondition` class is essentially the patch they need. Filing an issue
   is an outward-facing action — confirm with Jochen before posting.
2. Once a fixed `modelsearch` release exists: delete `src/cast/modelsearch_compat.py`,
   its call in `cast/apps.py`, and `tests/modelsearch_compat_test.py`; require the fixed
   version (or gate the shim on the broken version range); note the removal in the
   release notes.
