# Search Hardening Follow-Ups

## Status

Historical decision record. No active implementation slice remains.

Researched on 2026-06-02. Keep django-cast's current normalization-only guard
around modelsearch. Do not add a local database-exception backstop unless a new
confirmed PostgreSQL `tsquery` or null-byte failure appears in a supported
modelsearch release.

## Rationale

The original empty-lexeme failure is fixed upstream:

- `wagtail/django-modelsearch` PR
  [#92](https://github.com/wagtail/django-modelsearch/pull/92) filters empty
  split terms after whitespace/hyphen splitting.
- The fix shipped in `modelsearch` v1.2.1.
- django-cast requires `modelsearch>=1.2.2,<1.4`, so supported installations
  are already above the fixed release.
- The installed local dependency during research was `modelsearch` 1.3.1.

The local normalization guard should remain because it is still useful search
hardening and keeps existing fallback semantics predictable. This should still
be described as search hardening, not as a confirmed SQL injection fix.

## Current Local Behavior

django-cast now has a local modelsearch wrapper in `src/cast/search_utils.py`.
It normalizes public and admin search input before modelsearch sees it:

- strips null bytes,
- collapses whitespace and hyphen runs,
- strips edge whitespace,
- caps input length at 500 characters.

The helpers should keep their distinct empty-normalized fallback behavior:

- `safe_fulltext_queryset()` remains strict for public post search and returns
  `queryset.none()`; it is called by `PostFilterset.fulltext_search()` in
  `src/cast/filters.py`,
- `safe_modelsearch_results()` remains forgiving for authenticated audio/video
  admin search and returns the base queryset; it is called by
  `src/cast/views/audio.py` and `src/cast/views/video.py`.

## Backstop Decision

Do not add a backstop now. The current dependency floor already includes the
upstream fix, and no supported-version local failure has been confirmed.

If a future backstop is added, it must handle modelsearch laziness. A
`try` / `except` around search object construction is not enough because
failures can occur later during `.count()`, pagination, or iteration.

Future constraints for any backstop:

- keep the catch narrow,
- catch only confirmed modelsearch/PostgreSQL failures, such as SQLSTATE
  `42601` with a `syntax error in tsquery` message,
- treat null-byte failures as confirmed only if the driver/SQLSTATE/message
  explicitly identifies NUL/null-byte input,
- wrap guarded evaluation in a transaction savepoint so a handled
  `ProgrammingError` or database error does not poison the surrounding request
  transaction,
- keep public search fallback strict (`queryset.none()`),
- keep authenticated media admin fallback forgiving (base queryset).

## Upstream Issue Decision

Do not file the old proposed upstream issue. It would duplicate already-fixed
upstream issue
[#89](https://github.com/wagtail/django-modelsearch/issues/89) / PR
[#92](https://github.com/wagtail/django-modelsearch/pull/92).

There is a newer open upstream issue,
[#98](https://github.com/wagtail/django-modelsearch/issues/98), that overlaps
the old empty-term report and also mentions punctuation-shaped inputs. If
django-cast engages upstream, comment there instead of filing a new issue, and
clarify that empty split terms are fixed in v1.2.1+ while any remaining
punctuation failure needs reproduction against current `modelsearch`.

## Future Test Shape

If a future implementation adds a backstop, tests that do not require
PostgreSQL should cover:

- normalization of null bytes, edge hyphens, repeated separators,
  scanner-shaped input, length caps, and Unicode,
- narrow exception classification with synthetic database exceptions,
- fake lazy search results that raise during `.count()`, slicing/pagination, and
  iteration,
- public fallback to `none()` and authenticated media admin fallback to the base
  queryset,
- re-raising nonmatching database/search errors.

Tests that require PostgreSQL should cover:

- `-foo`, `foo-`, `--`, scanner-shaped leading/trailing hyphen input,
  `foo--bar`, punctuation-shaped input, normal searches, and Unicode,
- a handled `tsquery` failure inside an outer transaction followed by another
  successful query to prove the transaction is not poisoned.
