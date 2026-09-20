# Paged feeds: research, migration concept, and implementation plan

Policy update: five-minute cache staleness is accepted, not a repair requirement.
The [selection-service plan](2026-09-19-paged-feeds-selection.md) supersedes older
immediate-revocation/no-store requirements. Selection implementation is approved;
public endpoints and subscription migration remain later slices.

Status: first investigation slice approved and implemented; runtime pagination
not yet approved. Research checked 2026-09-19; two-round independent research
review complete with advisory findings addressed. The [slice 1 record](2026-09-19-paged-feeds-slice1.md)
contains measurements and concrete contracts that supersede open questions below.
No production feed behavior changes in this work.

## Purpose and scope

Support large archives across django-cast installations, not only the maintainer's
sites. Bound the work and response size of an individual feed request while
allowing clients to retrieve older entries. This is feed infrastructure, not a
theme project. Include blog RSS/Atom and podcast RSS/Atom in each audio format.
Do not add a new JSON feed format, change episode identities, or implement an
immutable archival/snapshot service in the first release.

## Evidence and confidence

### Existing django-cast behavior

Inspected at `56c4d5a4`:

- `src/cast/feeds.py`: `RepositoryMixin.items()` returns the full repository
  queryset. Both repository paths select live/public descendants in descending
  `visible_date` order; podcasts additionally require podcast audio. No item cap.
- `src/cast/models/repository/contexts.py`: `data_for_feed_cachable()` explicitly
  calls the builder with `is_paginated=False`. Rendering only a slice afterwards
  would still load the whole archive, defeating the principal performance goal.
- `src/cast/urls.py`: four XML routes have a five-minute response cache, with
  the root's public-access check outside that cache. Feed instances are request-local.
- `feed_url()` currently drops query parameters. A continuation URL must not be
  serialized as the root `self` link. Existing item GUIDs are based on post UUIDs;
  Atom podcast identity is explicitly anchored to the blog URL.
- `Post.visible_date` is non-nullable and has an individual database index in
  the current model. That alone does not establish the cost of the proposed
  compound ordering with Wagtail's joins/access filters.
- `docs/features/feeds.rst` advertises `CAST_FEED_ITEM_LIMIT` and
  `CAST_FEED_CACHE_TIMEOUT`, but neither setting is implemented. Correct these
  claims as a separate docs correction, not by quietly adopting them as a
  backwards-compatible contract. Check related performance documentation too;
  this correction is tracked independently of approval for pagination.

### Standards and implementation evidence

Sources below are primary sources. Source inspection is not an end-to-end client test.

| Source | Observation | What it does not establish |
| --- | --- | --- |
| [RFC 5005](https://www.rfc-editor.org/rfc/rfc5005.html), sections 2–4 and appendix B | Paged feeds use navigation relations including `next`, `previous`, `first`, `last`; RSS can use Atom namespace links. At least one navigation relation is required. Pages are explicitly not a coherent snapshot. Archived feeds are a distinct mechanism with more stable membership. | Universal reader support or lossless traversal while content changes |
| [Podlove guidance](https://podlove.org/paged-feeds/) | Recommends paged podcast feeds for large archives | Its historical proxy examples are not current compatibility certification |
| [Podlove Publisher RSS source](https://github.com/podlove/podlove-publisher/blob/b80dcc47f6a9e664cb3fa64dda0d6d5df4f8cc12/lib/feeds/rss.php) | Emits `next`, `prev`, `first`, `last` links and uses numbered offset pages; [canonical URL helper](https://github.com/podlove/podlove-publisher/blob/b80dcc47f6a9e664cb3fa64dda0d6d5df4f8cc12/lib/feeds.php) retains `paged` | Not all details should be copied: RFC 5005 spells the backward relation `previous`, unlike this implementation's `prev` |
| [AntennaPod Atom parser](https://github.com/AntennaPod/AntennaPod/blob/791078530e9f3a55969b9d424c9af392e5349534/parser/feed/src/main/java/de/danoeh/antennapod/parser/feed/namespace/Atom.java) | Recognizes `rel="next"`, marks the feed paged and stores the next URL | Does not establish behavior of a particular installed release |
| [AntennaPod update worker](https://github.com/AntennaPod/AntennaPod/blob/791078530e9f3a55969b9d424c9af392e5349534/net/download/service/src/main/java/de/danoeh/antennapod/net/download/service/feed/FeedUpdateWorker.java) | A next-page operation fetches that stored URL | Does not prove all pages are automatically fetched at subscription time |
| [Apple feed requirements](https://podcasters.apple.com/support/823-podcast-requirements) | Requires stable episode GUIDs and valid enclosures; inspected page does not promise RFC 5005 traversal | Absence of a promise is not proof of non-support |
| [Pocket Casts: missing old episodes](https://support.pocketcasts.com/knowledge-base/missing-old-episodes/) | Describes feed availability and app-local archived episodes | “Show Archived” is not evidence of RFC 5005 archived/paged feed retrieval |

Compatibility classification: AntennaPod has concrete source evidence; Apple
Podcasts, Pocket Casts, Spotify, Overcast and general-purpose readers remain
unverified for this feature. No client was installed/tested, no test subscription
was submitted to a directory, and no vendor was contacted. Do not advertise a
verified client matrix yet. Podcast archive preservation must not depend on
assuming support from this evidence.

## Recommended concept

### 1. Additive first, explicit migration later

Keep existing feed URLs and their full-content behavior by default. Add parallel
paged endpoints, for example `/<slug>/feed/paged/rss.xml` and
`/<slug>/feed/podcast/<format>/paged/rss.xml`, with Atom equivalents. Provide a
per-blog/podcast opt-in configuration, not automatic activation based on size.
Initially expose these URLs through operator documentation; no template work.

Also reserve explicit full-feed endpoints for the migration stage. They must
remain available when an operator later changes an existing subscription URL to
paged mode. Do not redirect subscriptions, change GUIDs, or emit platform-specific
feed-move tags automatically. A full-feed alternative does not make migration
transparent to clients that never discover/use it.

### 2. Forward keyset pagination, not deep numbered offsets

Proposed page size: 100 entries, configurable per feed owner with a documented
upper bound (proposed 500). These are design defaults, not measured optimal sizes.
Select by `(-visible_date, -pk)` with a strict older-than tuple boundary and fetch
at most N+1 records to detect another page. Slice before constructing either
repository or loading media/rendering data. Do not count the entire archive for
each request or offer a page-number jump UI.

Use a versioned, size-bounded opaque cursor in `?cursor=...`, binding the blog ID,
feed kind, audio format, URL family, ordering version and last tuple. Page size
comes from current policy: changing it must not invalidate the boundary. Signing
is required to reject forged query state, not as authorization. Never encode
credentials or accept an arbitrary URL/SQL expression from the cursor. Require
normal live/public checks for every request. No automatic time expiry: clients
may return months later. Retain old decoder versions and signing fallback keys
while practical. Emergency key revocation can still invalidate a continuation;
there is no unconditional perpetual-validity promise. Define the recovery table
in slice 1: oversized/malformed or verified wrong-owner/format/family inputs get
a bounded, non-cacheable 400; a well-shaped but retired/unsupported cursor gets
a non-cacheable 302 to the validated paged head, without accepting its boundary.
Unverifiable signatures must never authorize a boundary and may use that same
safe head redirect (the server cannot distinguish retirement from tampering).
Test real clients' redirect/restart handling; restarting may repeat entries or
fail to recover their prior position. Do not describe a prose 400 body as
automatic client recovery. No redirect destination comes from cursor data.

Recovery precedence: a valid signature with wrong owner/kind/format fails first.
For an otherwise matching identity, an explicitly retired family/decoder takes
the safe-head recovery path; an active family used on a different family's route
is a 400. Retired-family recovery requires keeping an explicit compatibility
route/alias; a removed route cannot redirect. Slice 1 must freeze that routing
retention contract rather than promising recovery from arbitrary removed URLs.

Emit an absolute, canonical `self` for the current document, `first` for the paged
head on every paged document, and `next` only when older items remain. Thus a
single-page or empty feed still has a navigation relation. Omit `last` and
backward navigation initially; this is a deliberate simplification to avoid
counts/reverse traversal. Links use the current validated host and feed format,
not a client-supplied URL. Preserve existing logical feed IDs across its pages,
and exact item GUID/enclosure values across full and paged representations.
Full and paged representations share the existing logical Atom identity, not
their document `self` URLs. Freeze the exact current identity for blog Atom as
well as podcast Atom before adding query parameters. Each URL family has its own
head (`first`) and per-document `self` including the canonical cursor; cursor
family binding prevents accidental cross-family continuation reuse.

New entries ahead of the cursor don't move the already-consumed boundary. Equal
timestamps are resolved by primary key purely for deterministic ordering, not
as a claim of publication/insertion chronology. Use UTC-normalized timestamp
values at database precision. Slice 1 must verify field nullability and legacy
data; if null dates are possible, specify a deterministic null partition and
cursor representation rather than silently dropping such entries. This is NOT an immutable snapshot:
backdating, date edits, republishing, deletion and restriction changes can affect
membership and cause omissions/duplicates across a traversal. Clients deduplicate
by GUID and refresh the head for new entries. Do not claim archival completeness
or add `fh:complete`/`fh:archive` merely because all pages can be walked.

### 3. Cache, access, and configuration

Retain the root public-access check before any cache lookup. Continuations are
public feed requests, not a bypass or a grant to view formerly public entries.
Preserve site isolation, audio format isolation, host handling and request-local
feed instances. Page metadata must be per request, not mutable global state.

New paged response cache keys must include normalized cursor, representation,
host/site, feed identity and effective configuration generation. Validate cursor
syntax/size before caching and do not let arbitrary query strings create cache
variants. Existing full-feed caching remains unchanged unless an approved repair
requires otherwise. Define policy-change cache invalidation before enabling an
existing URL's migration; stale full and paged responses must not cross modes.

Entry deletion/unpublishing/restriction requires particular care: the root guard
alone does not invalidate already-cached child entries. First implementation must
measure the existing behavior, then define/test a bounded invalidation or live
membership revalidation strategy for paged responses. Reproduce and triage the
full-feed case independently: if confirmed, record an all-feed repair/policy
decision even if pagination is never approved. This investigation has a separate
backlog entry; it is not yet a confirmed new vulnerability. Do not advertise immediate
revocation based solely on a five-minute TTL. This is an explicit design gate,
not permission to introduce a second independently stale content cache.

Recommend a settings-backed per-site-and-blog-path policy first (mode, page size, generation)
to avoid an admin UI/schema project. Validate positive bounded page sizes and
unknown modes at startup; default all owners to legacy/full behavior. Validate
selectors against actual sites/blogs with a deployment check after migrations:
unknown/ambiguous targets are errors, not silent no-ops. Avoid database queries
in application startup. Define rename/move procedures, staging overrides, and
handling of retired selectors before shipping. Database PKs remain suitable for
runtime cursor binding but are not portable operator configuration keys. Confirm
configuration ergonomics with multi-site consumers before freezing names. No
proposed setting is an existing public API. Freeze HTTP caching semantics in
slice 1 too: paged documents are mutable, not immutable archives. Cover
Cache-Control, any ETag/Last-Modified and conditional 304 behavior, including
membership changes and policy generations. Do not reuse a validator derived
only from the newest publication timestamp when older entries can change.

## Migration and rollback

1. Deploy additive endpoints with existing subscriptions untouched. Validate XML,
   stable GUIDs, full-vs-paged item parity and bounded work on synthetic archives.
2. Test a dedicated public staging feed in target clients: fresh subscription,
   fetching older pages, refresh after publication, edits to old items, and resume
   after cursor/key/config changes. Record app version/date, actual feed requests
   and observed counts. A desktop/UI session and external directory submissions
   need separate scheduling/authorization; research does not claim these tests.
3. Keep legacy/full as the recommended default when clients are unverified.
   Operators can offer paged URLs separately without migrating existing listeners.
4. Only after explicit operator acceptance, serve the paged head at the original
   subscription URL. Keep the head's `self` at that URL and continuations' `self`
   at their full canonical URLs, preserve logical/item identity,
   and generate continuation/first links consistently for that URL family.
   Explain that old items may disappear for non-paging clients, including fresh
   subscribers; retained client caches are not a guarantee. Announce a full-feed
   alternative before switching. This is a behavior change, not a safe default
   upgrade or a transparent redirect.
5. Roll back by restoring full output at the original URL and invalidating the
   affected caches. Keep additive paged endpoints and the routing for old-family
   continuations: valid cursors continue paging even when that family's bare
   head returns full output. A mode-only rollback must not rotate keys, change
   decoder versions, or invalidate cursors. Other invalidation events follow the
   recovery contract above, not a guarantee of uninterrupted traversal. Do not promise to
   restore client-specific played/downloaded state or automatic catalog recovery.

Trade-off: preserving a full feed retains its unbounded rendering cost for clients
using it. Pagination improves adopters' requests; it does not eliminate every
large response. No implementation can both force unaware clients onto partial
feeds and guarantee those clients still discover the entire archive.

## Implementation slices and acceptance gates

Each implementation slice needs tests, docs/release notes, `just check` (100%
coverage), applicable dependency checks, and independent review before commit.
No commits, release, or implementation are authorized by this research alone.

1. **Baseline and contract spike:** link the independently tracked feed docs and
   warm-cache investigations; add
   regressions for current full-feed membership and identities on all four feed
   types/both repository modes. Reproduce child-entry revocation against warm
   caches. Use disposable 1k/10k-entry datasets to measure SQL, rendered-entry
   counts, peak memory, response bytes and cold/warm latency (not production DBs).
   Inspect nullability/timezone behavior and database query plans on SQLite and
   PostgreSQL, including deep cursors. Decide whether an index migration is needed;
   account for Wagtail inheritance/joins and descendant/access filters rather than
   assuming one composite index covers them all. N+1 bounds hydration, not total
   SQL scan work. Finalize settings/cursor/key rotation/cache invalidation and HTTP
   validator contracts; independently
   review those concrete decisions before proceeding. Performance timings are
   measurements, not brittle CI thresholds.
2. **Selection service:** shared public queryset and keyset selection with N+1;
   adapt both repositories to accept only selected entries. Cover zero/one/N/N+1,
   equal dates, newer inserts, deletions, backdating, malformed/cross-owner/cross-
   format cursors and page-size changes. Keep existing endpoints full. Assert
   only N entries are hydrated/rendered, not just that XML contains N entries.
3. **Additive RSS/Atom endpoints:** shared pagination metadata with serializer
   adapters; proper namespaces/MIME types, self/first/next, identities, podcast
   metadata, chapters/transcripts and format-specific enclosures unchanged. Test
   root/child restrictions, host aliases, cache boundaries, parallel requests,
   invalid query inputs and cursor recovery. Document operator-only opt-in.
4. **Parser checks and installed-client interoperability:** fixtures establish
   XML acceptance/link extraction only. Publish that parser matrix separately
   from installed-app tests (version/date, observed requests and archive counts).
   At minimum schedule an installed AntennaPod traversal/refresh/recovery test and
   a non-paging parser control; test major target apps where available. If an app
   session is unavailable, leave its gate pending and label support unverified.
   Unknowns stay unknown; source evidence cannot close an installed-app gate.
5. **Existing-URL migration:** implement explicit per-owner mode switch/full
   alternative, cache invalidation and rollback only after the previous evidence
   is reviewed. Test old subscriptions, fresh subscriptions, continuation URLs
   issued before rollback, and unchanged identity. No automatic site migration.

## Decisions still requiring approval/evidence

- Approve additive-first, no default behavior change, and forward-only keysets.
- Final setting names, scope and limits; signing-key/cursor recovery contract.
- Child-entry cache revocation strategy and measured large-archive query plan.
- Which client versions will receive end-to-end testing before support claims.
- Whether/when to ship existing-URL migration after additive support; the concept
  does not treat unknown client compatibility as a blocker to additive endpoints.

## Review record

Claude Opus, high effort, direct isolated review, two rounds on 2026-09-19.
Round 1: one Critical, seven Warnings, four Suggestions. Required findings
addressed cursor durability/recovery, independent cache triage, signing, ordering
and index investigation, backlog delivery criteria, evidence levels and portable
configuration. Three Suggestions clarified identity, independent docs cleanup,
and HTTP validators. The out-of-scope rich-text suggestion was rejected: the
unchanged API reference already contains downstream re-enablement guidance.

Round 2 independently reviewed the repair delta: no Critical/Warning findings,
two Suggestions. Both addressed by clarifying retired-family recovery precedence
and making the backlog checkbox require delivery, not merely research approval.
Stop at advisory convergence: these final clarifications do not warrant another
agreement-seeking review. This is an advisory closure, not a CLEAN verdict or
evidence of actual client interoperability. Neither round omitted or redacted
review content. Artifacts: `/tmp/cast-paged-feed-research.xAi3gB/` (local/ephemeral).

Validation: `just check` passed with 100% coverage; subsequent changes are planning
prose only and pass `git diff --check`. Existing uncommitted rich-text deferral
notes were preserved. No source code, feeds, templates, commits or deployments
were changed by this research.
