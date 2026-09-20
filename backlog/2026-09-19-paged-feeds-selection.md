# Paged feeds: selection-service slice

Status: internal service implemented and verified; independent plan and code
review cycles closed with advisory dispositions.
This record supersedes earlier cache-repair/no-store requirements in the research
and spike notes. The user accepts five-minute stale feed content as normal caching.
Do not remove caching or introduce immediate revocation as a feature prerequisite.

## Scope

Internal service only: no URLs, new settings, HTTP adapters, public pagination,
subscription migration or cache changes. Existing full feeds keep their exact
selection and caching behavior. Five-minute caching with cursor/host/format/config
isolation is proposed for a later endpoint slice, pending its own review;
validator/recovery behavior will be tested there. Immediate revocation is not a
prerequisite. The [rejected cache-repair proposal](2026-09-19-feed-cache-policy.md)
is retained for history. Its former BACKLOG.md index entry and the completed
feed-doc-correction index entry were removed; neither remains active work.

## Implementation contract

- Select live/public descendants of a freshly checked live/public Blog; podcasts
  additionally require podcast audio. Caller supplies a validated Site/Blog
  identity; service checks actual site containment and fresh root restrictions.
- Require USE_TZ=True for this new internal service; naive local timestamps can
  be ambiguous during DST transitions and must not be silently reinterpreted as
  UTC. Existing full feeds are unaffected. This precondition is documented and tested.
- Order by descending (visible_date, pk), select N+1 date/ID tuples, and hydrate
  only the first N via an ID-constrained queryset with the same descending date/pk
  ordering. N is an integer 1–500, default
  100. No COUNT or OFFSET. No snapshot guarantee across database queries/requests.
- Encapsulate a parameterized row-tuple comparison using Django expressions on
  SQLite/PostgreSQL, with a logically equivalent OR fallback on other backends.
  Add a Post(visible_date, page_ptr) index; keep the old individual index.
- Immutable scope binds site/blog IDs, kind, representation, audio format, family
  and ordering version. Signed, uncompressed, size-bounded cursor contains scope
  and UTC microsecond timestamp/pk. Page size is not bound. Django Signer uses a
  dedicated salt and SECRET_KEY_FALLBACKS without TTL. No URL or authorization
  comes from a cursor. Strict field/type/date validation, positive bounded IDs.
- Distinguish malformed/wrong-scope cursor (InvalidFeedCursor) from unverifiable
  or unsupported cursor (RestartFeedCursor); neither admits a boundary. Only
  future HTTP adapters map these to 400 or safe-head 302 after root checks.
  Validate envelope syntax/size before signature verification; decode signed
  payload structure after verification. Future unknown versions restart without
  interpreting an unknown schema. Active-family mismatch is invalid.
- Return immutable selected IDs and next cursor. A service helper constructs a
  FeedContext in either repository mode from only the selected queryset. Already
  supported repository constructors stay intact; no unbounded fallback on empty
  selection. The lookahead item is never hydrated/rendered.
- Concurrent edits may produce a shorter page, repeats or omissions, as ordinary
  non-snapshot feeds do. A next cursor is based on the original selected boundary,
  not on a mutable hydrated object's later timestamp.

## Verification and delivery

Tests: zero/one/N/N+1, date ties, multi-owner filtering, new inserts, deleted
boundary, backdating, page-size change, malformed/tampered/foreign cursors, key
rotation, unsupported versions, root/child restrictions and both repositories.
Assert selection SQL limit, absence of count/offset, and actual hydration/render
counts. Test row comparison and fallback independently, SQLite/PostgreSQL focused
runs and query plans, migration consistency. Existing full-feed tests unchanged
apart from accepted-cache terminology. Run just check (100%), docs build, and
independent code review. Update feed documentation and docs/releases/0.2.66.rst
to describe the internal service and required index migration (including table
locking considerations); a docs build alone is not sufficient. Update the baseline
module/test docstrings and rename its visibility characterization test to record
accepted cache staleness rather than a pending repair.

Consumers were inspected: homepage and python-podcast depend on develop. Their
next dependency upgrade needs the normal migrate step for the added index; no
settings/schema data changes or sibling code changes. Index creation may lock a
large table; schedule migrations appropriately. No feed URLs/templates change.

## Review and validation record

Plan reviewed by Opus/high in two valid rounds: two accepted Warnings clarified
and independently verified; one alleged remaining backlog entry rejected after
checking the current file (it was an uncommitted addition removed before review).
Suggestions on hydration ordering, baseline wording and historical linking were
addressed. Final plan verdict was advisory-only, not CLEAN; no evidence omissions.

The internal module is `src/cast/feed_selection.py`; migration 0083 adds the index.
Initial focused runs: 78 cases passed on SQLite and PostgreSQL 17, with PostgreSQL
applying real migrations. The final tree has 79 focused cases, all passing.
The existing PostgreSQL CI job now includes selection tests, with no new job.
Commit, push and CI verification were authorized after local review closure.

Local disposable verification/review artifacts: `/tmp/cast-feed-selection.0RBCCb/`.

Follow-up verification: 79 focused cases pass on PostgreSQL 17 and on the oldest
supported combination (Django 5.2.17 / Wagtail 7.0.9) with real migrations. The
final full check passes at 100% coverage. Sphinx warnings-as-errors build and
makemigrations consistency check pass.

Actual-service plans on disposable 1k/10k datasets reproduce the spike's result:
PostgreSQL uses `cast_post_feed_boundary_idx` with a row-comparison Index Cond;
SQLite chooses a covering visible-date index SEARCH for the deep boundary. No
constant scan-work claim is made. Verification caught two compiler details:
Boolean Func filtering added `= 1` on SQLite (preventing the desired seek), and
Episode inheritance trimmed parent-key references onto the Episode table. A
Lookup avoids the boolean wrapper; selection now starts on Post and joins Episode
only for audio eligibility. Hydration uses a bounded, public-filtered ID subquery
to load concrete Episodes. These material adjustments were independently reviewed
in the second code-review round.

Code review: Opus/high, two valid rounds, no skipped/truncated/redacted evidence.
The first round's Warning about Meta inheritance was disproved by Django system
checks, migration consistency checks on current and oldest supported stacks,
and model introspection: only Post owns the index; Episode has none. Both initial
Suggestions were addressed (dedicated cursor exceptions and zero-query empty
metadata regression). The second round verified the material query/hydration
delta and left no Critical/Warning. Its two Suggestions were adjudicated:

- Documented that the four-operand Lookup is deliberately not registered.
- Deferred making its operand containers usable in aggregation: this private
  selector never aggregates or exposes its queryset, and row GROUP BY behavior
  would require separate backend validation. No supported path compiles those
  containers directly; this is future-extension hardening, not a current defect.

Advisory closure, not a CLEAN verdict. Stop because no material unresolved risk
remains in this slice. Artifacts: `plan-review*/result.json`, `code-review*/result.json`.
Final `just check`: 3,064 passed, five skipped, 100% coverage; PostgreSQL focused
run: 79 passed. Docs build, migration checks and oldest-pair focused tests pass.
Disposable PostgreSQL was stopped after verification. No user database was used.
