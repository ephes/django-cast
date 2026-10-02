# Scoped security audit: Podlove authenticated response caching

Date: 2026-10-03

Status: Implemented and independently reviewed within the scope below. Local
commit/integration is coordinated separately; deployment and owner acceptance
remain pending.

## Scope and threat model

This bounded local audit inspected prior fixed security notes
([June review](2026-06-23-security-review.md) and
[September review](2026-09-07-security-review.md)) before inspecting public
media IDs, upload ingestion, feed authorization/cache boundaries, and relevant
Wagtail permissions. Anonymous callers, authenticated restricted-page readers,
and editors were considered separately. Only synthetic local test data was used.

The concrete repair scope is the legacy Podlove audio detail API. It authorizes
through a referencing live/viewable page or an editable draft, and validates all
supplied anchors. Its successful private responses lacked an explicit cache
policy. A host using Django's documented full-site cache middleware could cache
such responses and return them without re-running authentication or permission
checks after access was revoked.

## Proven finding

Medium: previously authorized draft/restricted Podlove detail responses remain
available to the same cache identity after credential or group-access revocation,
for the host cache lifetime. This is a revocation bypass, not a demonstrated
cross-user or anonymous disclosure.

Reproduction uses Django's actual UpdateCacheMiddleware / FetchFromCacheMiddleware,
default DRF BasicAuthentication, and session authentication for the group case:

1. An editor with synthetic Basic credentials requests a draft audio's Podlove
   detail and gets 200. Rotate that account's password, then repeat the request
   with the old header: pre-fix response is cached 200. Clear the cache and repeat:
   the same old credentials return 403. Bare, path-post, and query-episode anchor
   variants all reproduce.
2. A synthetic reader belongs to a group permitted by a live episode restriction.
   Request Podlove detail using the reader's session, remove their group membership,
   and repeat: pre-fix cached 200; after clearing cache, the same session gets 404.

Final exploit-first regression tests were run with only application views
restored temporarily to the base version, then the repaired views restored:

```text
uv run pytest tests/media_cache_security_test.py -k 'revoked or membership' -q
4 failed, 3 deselected
```

Failures were cached 200 versus fresh 403/404, before response-header assertions.
The original Basic editor-to-anonymous replay hypothesis was negative on the
locked Django 6.1.1 environment: Django varies cached Authorization responses,
and the anonymous request gets 404. That variation does not recheck an identical
revoked credential or a session whose group access changed.

## Repair and regression coverage

The existing authorization helper's granting pages are retained for each anchor.
If any granting page is a draft or has direct/inherited view restrictions, the
response now has `Cache-Control: private, no-store` and `Vary: Cookie, Authorization`.
No URL, response-body contract, authorization policy, or dependency changed.
Public unrestricted responses keep their prior cache behavior. Existing cache
entries must be purged on deployment; response headers cannot evict content
already cached before the upgrade. This is documented without performing any
deployment or cache mutation outside the synthetic tests.

Seven new regressions cover the three draft anchor forms, group revocation,
both mixed public/private anchor orders, and cacheable public output. The fresh
uncached denial controls distinguish the exploit from ordinary permission checks.

## Validation and limits

- `uv sync --frozen` initially failed because `uv.lock` is ignored and missing in
  the new worktree. The existing original repository lock was copied read-only
  into the isolated worktree, then `uv sync --frozen` succeeded, creating its own
  local `.venv`. The copied lock is not committed; no dependency resolution change
  was made.
- `uv run pytest tests/media_cache_security_test.py tests/endpoint_authorization_test.py -q`:
  50 passed in 1.22 seconds, including seven new regressions.
- `just check`: Ruff passed; mypy passed for 163 source files; 3,072 tests
  passed and five skipped in 60.90 seconds. The skips are one inactive Wagtail v3
  experiment and four PostgreSQL-only row-lock checks under SQLite. Python
  statement/branch coverage is 100% (13,603 statements and 3,980 branches, zero
  misses or partial branches).
- `uv run sphinx-build -W -b html docs /tmp/cast-security-audit-docs`:
  succeeded without warnings.
- `git diff --check`: passed.
- No live-site requests, personal data, load tests, browser fuzzing, arbitrary host
  authentication/storage backend audits, deployment changes, or dependency audits
  were performed. This is not a comprehensive clean security verdict.
- Other legacy transcript/chapter views also lack an explicit private/no-store
  policy; they were inspected but were not reproduced or repaired in this slice.
  Their full-site-cache revocation behavior was unverified at the conclusion
  of this first slice. The subsequent bounded reproduction and repair are
  recorded in [the adjacent media audit](2026-10-03-adjacent-media-cache-audit.md).
  Existing custom player transcript private/no-store protection remains unchanged.

## Independent verification and review

The coordinator independently replayed the final four exploit-first tests in a
temporary checkout of committed base `0e55a47b`; all four failed at cached 200
versus fresh 403/404, before header assertions. A separate `UV_FROZEN=1 just check`
on the repaired isolated tree passed Ruff, mypy, 3,072 tests with five documented
skips, and 100% statement/branch coverage. Applicable pre-commit hooks passed
for all six touched files.

The installed supervised `codex-review-loop` returned `CLEAN (scoped)` with zero
findings using OpenAI `gpt-6.1-sol` at **high** effort. The harness proved that
model and effort from the session record, reported no forbidden tools, and
removed the throwaway review copy. Same-family independent review was explicitly
authorized. No Anthropic reviewer was invoked for this slice.

No files were skipped or truncated. The bundle redacted one synthetic fixture
password in the new test file; the repository copy excluded no files. The
redaction does not affect the access/cache semantics being assessed. This is a
clean result within the authored Podlove scope, not a whole-project security
assurance. No material findings remain in this gate, so another review would
add little risk-reduction value; the cycle stops after this valid review.
