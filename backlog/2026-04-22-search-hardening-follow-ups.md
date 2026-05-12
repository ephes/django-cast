# Search Hardening Follow-Ups

## Current State

django-cast now has a local modelsearch wrapper in `src/cast/search_utils.py`.
It normalizes public and admin search input before modelsearch sees it:

- strips null bytes,
- collapses whitespace and hyphen runs,
- strips edge whitespace,
- caps input length at 500 characters,
- returns no public results for empty-normalized post searches,
- returns the unfiltered base queryset for empty-normalized audio/video admin searches.

This addresses the production failure mode where scanner-shaped search input
caused PostgreSQL `tsquery` parse errors through modelsearch. This should be
described as search hardening, not as a confirmed SQL injection fix.

## Open Local Decision

Decide whether normalization is sufficient or whether the helpers should add a
database-exception backstop for confirmed `tsquery` / null-byte failures.

If a backstop is added, it must handle modelsearch laziness. A `try` / `except`
around search object construction is not enough because failures can occur later
during `.count()`, pagination, or iteration.

Preferred constraints for any backstop:

- keep the catch narrow,
- inspect PostgreSQL SQLSTATE and/or a `tsquery` marker where possible,
- use a transaction savepoint so a guarded `ProgrammingError` does not poison the surrounding request transaction,
- keep public search fallback strict (`queryset.none()`),
- keep authenticated media admin fallback forgiving (base queryset).

## Upstream Issue

File an issue against `https://github.com/wagtail/django-modelsearch/issues`.
The PyPI package is `modelsearch`; the GitHub repository is `django-modelsearch`.

Suggested title:

```text
PostgreSQL search backend should filter empty terms before building raw tsquery lexemes
```

Suggested issue body:

```text
The `modelsearch` PostgreSQL database search backend splits PlainText queries with
`re.split(r"[\s\-]+", query.query_string)` and then builds `Lexeme` objects from
each term. Inputs with leading/trailing hyphen separators, all-separator inputs,
and empty strings can produce empty terms, e.g. `-foo`, `foo-`, `--`, `""`, or
scanner-shaped strings like `-9399862) UNION ALL SELECT ... -- -`.

Those empty strings become `Lexeme("")`, which renders as an empty raw tsquery
lexeme. PostgreSQL rejects the generated raw tsquery with `syntax error in
tsquery`, causing an avoidable server error in applications that pass public
search input to modelsearch.

Filtering empty terms after splitting should prevent this:

`terms = [term for term in re.split(r"[\s\-]+", query.query_string) if term]`

If no terms remain, the backend should use its existing empty-query behavior
instead of constructing a raw tsquery.

Payloads from SQL-injection scanners hit this too because they often start with
`-`, but the failure is in raw tsquery parsing, not SQL parsing.
```

Suggested upstream regression cases:

- `-foo` should not raise.
- `foo-` should not raise.
- an empty string should not raise.
- `--` should not raise and should follow the backend's chosen empty-query behavior.
- a scanner-shaped query beginning and ending with hyphen separators should not raise a PostgreSQL `tsquery`
  syntax error.
- internal repeated separators such as `foo--bar` should keep current behavior.
- normal searches should keep existing behavior and ranking.
- Unicode terms should not be filtered out or ASCII-normalized.
