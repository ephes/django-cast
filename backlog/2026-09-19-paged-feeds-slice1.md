# Paged feeds — baseline and contract spike

Policy update: the user accepts five-minute cache staleness. The later
[selection-service plan](2026-09-19-paged-feeds-selection.md) supersedes this
record's no-store and full-feed repair requirements. Measurements remain valid.

Status: approved investigation implemented; independent review closed with an advisory. Runtime
pagination remains proposed, not enabled. This record refines the
[research concept](2026-09-19-paged-feeds.md); its concrete decisions take precedence.

## Baseline evidence

`tests/feed_baseline_test.py` adds 32 cases across both repository modes and all
four XML routes. Full feeds include 51 eligible entries, retain UUID GUIDs and
self URLs, and preserve Atom IDs and podcast m4a enclosures. Blog Atom identity
uses the request-host blog URL; podcast Atom uses the canonical blog URL. Preserve
these existing distinctions, not a newly invented feed-endpoint ID.
Baseline ordering is descending visible_date only; equal-date pk ordering is a
new pagination requirement, not an existing full-feed guarantee.

Deletion, unpublishing and adding a login restriction all leave the old child in
a warm XML cache; clearing the cache excludes it. This is characterization of an
existing problem, not desired behavior. Fix it separately across all full-feed
routes; replace the stale-output assertions when that repair lands. Root checks
already precede the response cache. Documentation now accurately describes this
and removes the unsupported feed-limit/cache-timeout settings.

## Disposable measurements (2026-09-19)

Opt-in `scripts/benchmark_feeds.py` reuses the typeahead seeder and isolated
settings, never a consumer database. Two blogs contain 1,000 and 10,000 public
posts plus restricted controls. Empty bodies and no media make this a lower-bound
workload, not a podcast/media performance certification. Runs use SQLite and a
disposable PostgreSQL 17 cluster. These are single, tracemalloc-instrumented local
samples, not CI thresholds or production latency estimates.

Representative 10,000-entry results (seconds / SQL queries / peak Python MiB):

| Database / repository | Full cold | Selected 100-entry prototype |
| --- | --- | --- |
| SQLite / default | 13.130 / 18 / 137.43 | 0.113 / 10 / 2.20 |
| SQLite / django | 11.091 / 16 / 168.99 | 0.098 / 8 / 1.82 |
| PostgreSQL / default | 13.314 / 18 / 155.89 | 0.119 / 10 / 2.25 |
| PostgreSQL / django | 11.347 / 16 / 169.02 | 0.100 / 8 / 1.81 |

Full responses render 10,000 entries and contain 8,464,115 bytes; selected
responses render 100 and contain 85,257 bytes. Warm full responses render zero
entries but still transfer the full XML (about 0.07 seconds, four queries and
42 MiB peak for django mode). At 1,000 entries, cold full feeds take about
1.1–1.4 seconds and contain 843,866 bytes.

The prototype selects 101 IDs before repository construction and hydrates only
100. It bypasses middleware, outer root checks, response caching and future
cursor/link processing. It is deliberately not a working endpoint or an
apples-to-apples speedup claim. Memory is Python allocation peak, not RSS;
response size is uncompressed XML, not measured network traffic. No paid CI
database service or benchmark job is added.

### Query plans and index decision

Selection queries include Wagtail inheritance joins, live/public restrictions and
descendant filtering. Plans are for PK-only N+1 selection, not subsequent media
hydration. The deep boundary is at 90% of each archive; OFFSET is used only to
prepare that experimental boundary, never proposed for runtime pagination.

On PostgreSQL, the OR-form keyset condition remains a filter even with the
candidate `(visible_date, page_ptr_id)` index. A row-tuple comparison with that
index becomes an index condition and removes the head's incremental sort. At
10k, tuple-deep selection was about 0.00030 seconds versus 0.00066 for OR with
the index. SQLite chose its existing visible-date covering index for tuple-deep
selection (about 0.00017 seconds), while OR chose a page scan and temporary sort
(about 0.00170 seconds), even with the candidate index available.

Decision: include a composite-index migration and parameterized tuple comparison
in the future selection slice, with SQLite/PostgreSQL plan verification. The
spike's `.extra()` SQL is experimental; implementation should use an encapsulated,
tested Django expression with backend handling. Do not claim O(N) scan work:
unrelated owners and restricted descendants may still be scanned. N+1 bounds
hydration, not examined database rows. Test skewed multi-owner data and equal-date
boundaries before calling selection ready. Keep existing individual index until
separate evidence supports removal.

`visible_date` is a non-nullable DateTimeField with `timezone.now` default and an
individual index. Normal ORM values in this USE_TZ setup are aware datetimes;
serialize UTC with six fractional digits and round-trip database precision. No
live/legacy consumer data was audited; unusual historical data needs preflight
before deployment, not a silent timestamp repair.

## Concrete proposed contracts for subsequent slices

These settings and endpoints are NOT implemented by this investigation.

- Configuration: `CAST_FEED_PAGINATION` is a list of records with exactly
  `hostname`, `port`, `blog_path`, `page_size`; absence means disabled. Hostname is
  canonical Wagtail Site hostname, port a positive integer, blog_path its
  site-relative URL path including leading/trailing slashes. Page size defaults
  to 100, range 1–500. Reject unknown fields, duplicates, booleans as integers,
  ambiguous sites and paths not resolving to a Blog. Perform database-dependent
  checks after migrations; never silently use Wagtail's fallback site. Resolve
  to site/blog IDs for requests. Renaming a site/path requires coordinated config
  update and an explicit URL alias, not automatic ownership transfer. No model
  fields or public editor controls in the first additive release.
- A normalized configuration fingerprint belongs in any future cache key, not
  cursor validity. Changing page size preserves continuation boundaries.
- Cursor: Django signing with a dedicated `cast.feeds.pagination.v1` salt;
  uncompressed JSON, version 1, maximum 1,024 encoded bytes. Bind site ID, blog
  ID, blog/podcast kind, RSS/Atom representation, audio format (null for blog),
  URL family, ordering version, and last `(visible_date, pk)` tuple. Use Signer,
  not timestamp expiry. Boundary pk is a positive integer; date must be UTC,
  finite and parseable at supported database precision. Reject unknown fields.
- Use SECRET_KEY and SECRET_KEY_FALLBACKS. Rotate by retaining prior verification
  keys while outstanding cursors need support; there is no automatic age cutoff
  or guaranteed perpetual validity. Emergency removal trades continuation for a
  safe restart. Never log raw cursors or embed secrets/URLs in payloads.
- Query handling: only one nonempty `cursor` parameter is accepted, or no query
  for the head. Unknown/duplicate parameters, overlong or malformed encodings and
  verified wrong site/owner/kind/format/representation get a bounded 400. After
  structural size checks, verify signatures before trusting any boundary. A
  well-shaped unverifiable signature or unsupported/retired version gets a 302
  to the validated current paged head. Wrong identity wins over retirement when
  the version is understood and signature verifies. No user-provided redirect.
- Families: keep explicit paged routes and their decoders for the entire period
  pagination remains configured. Later migration of the legacy head must not
  invalidate issued legacy-family continuations on rollback; retain its cursor
  dispatch while serving a full legacy head again. Retired families need an
  explicit compatibility route to restart at the paged head. Removing the whole
  opt-in configuration intentionally withdraws the additive endpoints (404);
  no recovery is promised after that operator action. Deleting/restricting the
  owner always wins over continuation/recovery.
- Caching/validators: initial paged endpoints have no shared response cache,
  send `Cache-Control: no-store` on success/errors/redirects, omit ETag and
  Last-Modified (including serializer-generated ones), and never return 304.
  Re-run root and child visibility for every page. No invalidation mechanism is
  needed for uncached paged responses; application/CDN configuration must not
  override no-store. Do not claim recall of bytes a client already downloaded.
  Existing full-feed cache repair is separately approved work. Add caching only
  with a reviewed freshness/invalidation design covering deletion, restrictions,
  publication, edits, media and configuration across workers.
- Pages are not snapshots. Edits/backdating can cause repeats or omissions;
  stable GUIDs allow deduplication but do not guarantee complete traversal.
  Keep the research concept's additive-first migration and real-client testing
  gate; do not switch an existing subscription URL on this benchmark's evidence.

## Reproduction and validation

For SQLite (creates only disposable data):

```sh
feed_spike_dir=$(mktemp -d /tmp/cast-feed-spike.XXXXXX)
CAST_BENCHMARK_DB_NAME="$feed_spike_dir/feeds.sqlite3" uv run python -m scripts.benchmark_feeds
CAST_BENCHMARK_DB_NAME="$feed_spike_dir/feeds.sqlite3" uv run python -m scripts.benchmark_feeds --selection-only --candidate-index
```

For PostgreSQL, initialize a fresh local cluster with TCP disabled and its Unix
socket in that mktemp directory, create only `cast_feed_spike`, then set
`CAST_BENCHMARK_DB_ENGINE=postgresql`, `CAST_BENCHMARK_DB_NAME=cast_feed_spike`,
`CAST_BENCHMARK_DB_HOST` to that directory and `CAST_BENCHMARK_DB_PORT` to its
chosen port. Run `uv run --with 'psycopg[binary]' python -m scripts.benchmark_feeds`,
then the selection-only/index variant. Stop that cluster afterwards. Never reuse
a consumer cluster. Candidate index creation is opt-in and disposable only.

Local detailed logs: `/tmp/cast-feed-spike.3VOC5m/` (`sqlite-final.log`,
`postgres-final.log`, `sqlite-plan.log`, `sqlite-index.log`, `pg-plan.log`,
`pg-index.log`). These are ephemeral; representative results are preserved above.
`just check` passed including 100% Python coverage; all 32 new cases passed.
The Sphinx HTML build passed with warnings treated as errors. The disposable
PostgreSQL cluster was stopped after measurement; its files remain in the local
artifact directory. Independent review results will be recorded below.

First valid independent review: Opus/high, two Warnings and six Suggestions,
with no omitted/redacted evidence. Added dataset-size checks before selection
measurement and a descending-date baseline assertion. Rejected the suggested
existing pk-tiebreak guarantee: current repository contexts order only by date.
Accepted fixture-separation assertion and cache-backend wording clarification.
Root-cache access already has regression coverage in `tests/feed_test.py`;
duplicate tests are unnecessary. Distinct per-episode audio mapping is deferred
to the additive serializer slice; this baseline only freezes enclosure values.
The rich-text index caveat is outside this slice and its linked note already
records downstream uncertainty. New files must accompany tracked edits in a
future commit; none is requested now.

Repair-delta review: Opus/high confirmed both Warning repairs; no Critical or
Warning remains, no omitted/redacted evidence. One Suggestion remains: explicitly
guard distinct fixture timestamps against future fixture drift. Deferred as
low-impact test hardening: current generated timestamps exercise descending
ordering, while deliberately equal-date cases belong to the selection slice.
Stop under the value-driven rule; this is advisory closure, not a CLEAN verdict.
Artifacts: `review2/result.json` and `review3/result.json` under the local log
directory above. An earlier attempt was INVALID after an out-of-scope read
request and is not counted as a valid review. No reviewer subagents were used.
