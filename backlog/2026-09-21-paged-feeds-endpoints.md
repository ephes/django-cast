# Paged feeds: additive HTTP endpoint contract

Status: implemented and independently reviewed, 2026-09-27. This is the retained
contract and implementation record, not an active implementation backlog.
All three implementation slices passed their review gates and local validation
(see Implementation progress). Client interoperability and subscription migration
remain separate, unapproved follow-ups.
No subscription changes or consumer opt-ins exist.
Based on the implemented [selection service](2026-09-19-paged-feeds-selection.md).
This contract supersedes the spike's no-store-success/cache-repair proposal:
five-minute stale child content is accepted ordinary caching, not a defect.

## Scope and route contract

Add four opt-in routes beneath the existing `cast.urls` mount:

| Relative route | URL name |
| --- | --- |
| `<slug>/feed/paged/rss.xml` | `paged_entries_feed` |
| `<slug>/feed/paged/atom.xml` | `paged_entries_atom_feed` |
| `<slug>/feed/podcast/<audio_format>/paged/rss.xml` | `paged_podcast_feed_rss` |
| `<slug>/feed/podcast/<audio_format>/paged/atom.xml` | `paged_podcast_feed_atom` |

GET and HEAD only; other methods return 405 with Allow. HEAD has GET's status
and representation headers, but no body (a cold HEAD may build the representation).
Use URL reversing, including the mount prefix; never hard-code `/blogs/` or `/`.
Keep all legacy routes, URL names, feed-detail links and autodiscovery unchanged.
No new full-feed aliases, legacy mode switch, directory submissions or redirects
from old subscriptions in this slice. Existing full feeds remain the default.

## Operator opt-in and ownership

Proposed setting `CAST_FEED_PAGINATION = []`. Each record has required `hostname`,
`port`, `blog_path`, and optional `page_size` (default 100, exact int 1–500).
Reject unknown fields, duplicates and booleans as integers. Require USE_TZ=True
only when configured. Port is an exact int 1–65535; hostname is a bare normalized
host, not a URL. `blog_path` is the canonical site-relative Wagtail page URL,
including leading/trailing slashes, not the Cast feed URL. Reject query/fragment,
dot segments and noncanonical paths. Document examples for a root Blog (`/`)
and a nested Blog. A Podcast record enables its blog and podcast feeds in all
currently supported audio formats; a non-Podcast has only the two blog feeds.

Resolve an exact unique Wagtail Site by hostname and port, then a unique Blog
at that path under its root (inclusive). Do not use default-Site fallback to
enable a feed. Slug-only routes cannot distinguish duplicate Blog slugs on one
site: reject ambiguous configured targets rather than picking the first. Use
the same resolution rule in checks and requests. Match the resolved Blog's slug
to the route; podcast routes additionally require a Podcast and known format.
Fresh live/public root and inherited restriction checks precede response-cache
lookup and cursor-error recovery. Disabled, missing, ambiguous or inaccessible
targets return 404; malformed global configuration raises ImproperlyConfigured.

For this first additive release only the configured exact hostname/port is
served, after Django ALLOWED_HOSTS validation; unconfigured aliases return 404,
even if Wagtail would select a default Site. Normalize case and trailing DNS dot
consistently; infer an omitted port from the validated request scheme. No
client-supplied forwarding headers beyond Django's explicitly trusted proxy
configuration. Require Site.find_for_request to agree with the exact matched
Site before handing off to the existing repository builder. No Site mutation.
This is deliberately stricter than legacy feeds, whose alias behavior is unchanged.

Add pure configuration system checks without database access during AppConfig
startup. Add explicitly database-enabled deployment checks for Site/path/slug
resolution, invoked after migrate with `check --deploy --database default`.
Do not query tables during ordinary pre-migration checks. Document failure IDs
and remedies, matching runtime fail-closed behavior. Renames/moves require config
updates; preserving old public URLs additionally requires operator-managed aliases.
No automatic transfer of cursor ownership to a replacement page at the old path.

## Query, links and identity

Accept an empty query for the head or exactly one nonempty `cursor` value. Reject
unknown keys, duplicates, empty cursor and malformed percent escapes with 400.
Bound the raw query to 4096 bytes before parsing, then apply the service's
1024-character cursor limit and strict envelope validation. Rebuild URLs with
standard URL encoding from the decoded accepted value, not the raw query string.
No `page`, client-controlled page size, redirect target or ordering parameter.

Reuse FeedScope family `paged` and existing decoder semantics, not a second
decoder. Site/blog/kind/representation/format remain bound to the cursor; page
size changes do not invalidate it. Validate cursors before cache lookup, including
signature verification: a cached response must not bypass signing-key removal.

| Condition after root/config checks | Response |
| --- | --- |
| Malformed input or verified wrong scope | Bounded generic 400 |
| Well-shaped unverifiable signature or unsupported version/order | 302 to reversed, validated same-feed paged head |
| Valid cursor with no remaining items | 200 empty feed, no next link |

Error text never echoes the cursor. Unknown schema versions follow the existing
decoder's restart behavior without trying to interpret unknown scope fields.
For understood schemas, verified scope mismatch wins over ordering retirement.
Recovery never authorizes a boundary or follows a cursor-supplied URL. No cursor
age expiry; key fallback retention and emergency retirement remain operator choices.

Every XML page has exactly one absolute `self` (including canonical cursor for
continuations), one `first` pointing to its bare paged head, and `next` only when
the service returns a next cursor. The head/empty feed still has `first`. Omit
`previous`, `last`, archive links and `fh:complete`/`fh:archive`. These are mutable
pages, not snapshots: concurrent edits can shorten pages or cause repeats/omissions.
Do not refill after hydration drops an item; keep the selected boundary for next.

Navigation uses Atom namespace links in RSS channel / Atom feed respectively,
with the corresponding representation MIME type. Extend generator root hooks
without duplicating self or losing podcast namespaces/extensions/stylesheets.
Feed instances and navigation metadata are request-local. Inject the bounded
FeedContext; never allow fallback to a full repository after it has been consumed.

Preserve existing logical Atom IDs across all pages and the full feed: blog
Atom uses the request-host blog URL, podcast Atom the existing canonical blog
URL. Do not substitute the paged endpoint or cursor URL as feed ID. Preserve
UUID item identities, item links/content/dates, distinct per-episode format-specific
enclosures (URL/length/MIME), iTunes and Podcasting 2.0 metadata, chapters and
transcripts. Compare with anonymous full-feed output under the same public theme.

## Cache and HTTP validators

Cache successful serialized representations for 300 seconds using Django's
configured default cache, in a new versioned namespace separate from legacy feeds.
No second repository-data cache or TTL extension on hits. Store bytes, safe
representation headers, ETag and generation time; never cache request, repository
or mutable feed instances. Key digest includes canonical absolute document URL
(scheme/host/port/mount/cursor), Site/Blog identity, kind/format/representation,
effective normalized policy including page size, repository mode, fixed language
and timezone (defined below). Include the active signing-key generation via a one-way digest so key
rotation cannot reuse cached next links signed by a removed key; never log keys.
Version the namespace when serialized semantics change across deployments.

Render with an isolated anonymous public request: no credentials, caller user,
session theme overrides or HTMX state may influence shared XML. Retain only the
validated origin, path and resolved Site; use the site's theme. For this first
release, fix rendering to Django settings.LANGUAGE_CODE and settings.TIME_ZONE,
using scoped translation/timezone overrides around repository construction and
serialization. Set the isolated request's LANGUAGE_CODE consistently and restore
the caller's active translation/timezone afterwards. Ignore Accept-Language,
django_language cookies, session/user timezone and middleware's negotiated active
language; no per-request language negotiation or per-Site language setting is
introduced. URL language prefixes, if deployed, remain part of the document URL
but do not override the fixed rendering language. Include both fixed setting
values in the origin cache key and ETag input, including for language-neutral XML.
Do not mutate the caller request.
Do not store responses with Set-Cookie or unexpected Vary headers. The permitted
Vary set is Accept-Encoding (compression) and Accept-Language (a redundant but
safe addition by LocaleMiddleware for this fixed-language representation).
Preserve these on downstream responses/304s; any other Vary, including Cookie,
precludes shared caching and must result in private, no-store output. Verify
this at the complete middleware boundary, not only before middleware runs.

Enforcement mechanism: add `cast.middleware.PagedFeedCacheMiddleware`, required
as the first entry in MIDDLEWARE only when pagination is configured. A pure
configuration check reports an error if it is absent or not first. It is
transparent for all non-paged routes. Its outermost response hook runs after
SessionMiddleware, CsrfViewMiddleware, LocaleMiddleware, ConditionalGetMiddleware
and GZipMiddleware on the return path. The adapter marks its responses/request
with private internal metadata; the hook finalizes both 200 and 304, and marks
paged errors/redirects no-store. Unexpected Vary or Set-Cookie forces private,
no-store and removes validators on either status. A private 304 does not gain a
body; it carries the no-store policy, so downstream caches cannot reuse it as a
public freshness extension. Do not delete cookies required by other middleware.

Defer origin-cache insertion until this final hook has accepted the final
response headers; the view only prepares a candidate on a cache miss. The
candidate contains a full 200 pre-compression anonymous XML representation and
whitelisted metadata, not the final compressed or cookie-bearing response. If a
cold conditional request ultimately returns 304, insert the full 200 candidate
after its final 304 headers pass the safety check; never store the 304 response
itself or a bodyless representation. A hit-derived 304 does not cause insertion
or renew TTL. Other non-200 outcomes discard any candidate. Test miss-then-304
insertion and subsequent unconditional hits. On an unsafe warm hit, also evict the origin key;
never reset TTL on a safe hit. Apply the same response check to hits and misses.
Document the mandatory middleware placement and test it with real session/CSRF
cookie-setting response hooks, compression and conditional requests. When
pagination is enabled, the pure check rejects Django's UpdateCacheMiddleware
and FetchFromCacheMiddleware anywhere in MIDDLEWARE (including subclasses),
avoiding both ordering conflicts and guard bypass. There is no built-in bypass
setting in this slice. Operators must remove those full-site cache middlewares
and use endpoint-specific caching; external proxies must follow the documented
path policy. Document this opt-in deployment constraint and test both checks.
No new middleware behavior applies to legacy full feeds.

Built-in
rendering must be shown deterministic across logged-in/anonymous requests; custom
templates are responsible for not depending on other unkeyed request inputs.

On 200, send `Cache-Control: public, max-age=300` and an Age reflecting time since
representation generation (not since this hit); do not reset downstream freshness
on every hit or on 304. Expired entries are regenerated, not served stale on errors.
Child deletion/restriction/unpublish/edit/media changes may remain visible in a
warm representation for that window. No immediate revocation claim. Fresh root
checks apply to requests reaching Django; browser/CDN caches cannot perform them.
CDNs must not bypass these guards at the origin or extend this freshness window;
document the required path exclusions/configuration. Django full-site cache
middleware is incompatible with this opt-in, as specified above.

Remove Django Feed.__call__'s item-date Last-Modified header on these new routes
only: a newest-item timestamp misses changes to older entries. Use a weak ETag
derived from the serialized bytes, canonical document URL and fixed language/
timezone settings, not max publication
date. Weak validation tolerates downstream compression differences. Apply
If-None-Match after current guards and cache lookup/rendering; matching GET/HEAD
returns bodyless 304 carrying ETag, Cache-Control, Age and relevant Vary. With no
Last-Modified, If-Modified-Since alone gets the ordinary representation. Verify
behavior through ConditionalGetMiddleware and GZipMiddleware, not just direct
views. XML publication/updated dates are preserved; they are not HTTP validators.
Errors/redirects/405 are uncached with `Cache-Control: no-store`, no validators;
conditional headers must not turn them into 304. Do not cache recovery responses.

## Implementation sequence after approval

1. Add setting parsing, pure/deployment checks and exact owner resolution; tests
   for disabled/default, root/nested paths, duplicate slugs, host/port/proxy cases.
2. Add shared paged view adapter using the existing selector/context builder,
   four request-local generator adapters and URL names. Add navigation and parity
   tests before caching; do not alter legacy classes' behavior.
3. Add the bounded response cache, required outermost finalization middleware,
   placement system check and conditional handling above; test complete
   middleware paths, cache partitioning and anonymous rendering isolation.
4. Update feed/settings/performance docs and current release notes, with opt-in,
   post-migration checks, key rotation, limitations and disable/rollback examples.
   Update this plan and BACKLOG to reflect implementation, not just test success.
5. Run just check (100%), locked Python 3.14 cold-cache mypy, Sphinx -W, focused
   oldest/latest dependency checks and existing PostgreSQL selection job. Reuse
   jobs; no additional Actions service, benchmark job or artifact uploads.
   Independently review code before any later commit request.

## Implementation progress

- Step 1 (implemented, independently reviewed): `src/cast/feed_pagination.py`
  parses and normalizes `CAST_FEED_PAGINATION` (default `[]`) without database
  access; `cast.E011` (malformed) and `cast.E012` (USE_TZ) are pure checks.
  `cast.E013`/`cast.E014` are deploy-only checks tagged solely `database`, so
  they run with `check --deploy --database default` and not during `migrate`,
  ordinary checks or `check --tag cast`. Resolution requires the exact Site
  hostname/port (no default-Site fallback), a Blog/Podcast at the root-relative
  path (inclusive root) and a slug unique among all Blog pages on that Site,
  drafts included. Request helpers validate the host through ALLOWED_HOSTS,
  infer an omitted port from the trusted scheme, require Site.find_for_request
  agreement and freshly recheck live/public access. Tests: `tests/feed_pagination_test.py`.
  Docs: internal-groundwork notes in feeds/settings docs and 0.2.66 release notes,
  with no operator opt-in promise.
  Independent review finding (accepted, repaired and re-reviewed): the parser
  had accepted a top-level tuple and any `Mapping` record. It now requires a
  `list` of `dict` records, with regression tests for empty/non-empty tuples,
  `MappingProxyType` and `UserDict` across parser, checks and request entry.
  Implementer: Claude Code Opus 5.5 / medium. Reviewer: Codex GPT-6 Sol / medium,
  two valid rounds; the repair review returned CLEAN with no evidence omissions.
  An earlier harness launch failed before review under the old system Python;
  using the project's Python resolved that invocation issue.
- Step 2 (implemented, independently reviewed): internal
  `src/cast/paged_feeds.py`. `admit_paged_feed_request` resolves the owner with
  the step-1 resolver (404 first), reverses the planned URL name under the
  `cast` namespace (mount, script and request-path language prefix; no rendering
  language), requires the request path to equal it, then admits the raw query:
  4096-byte bound, ASCII, complete percent escapes, strict UTF-8, empty or exactly
  one nonempty `cursor`. `InvalidPagedFeedQuery` subclasses `InvalidFeedCursor`,
  so decoder distinctions stay intact (400 vs. restart). `select_paged_feed`
  reuses `select_feed_page` with the record's page size; `render_paged_feed`
  reuses `build_feed_page_context` in an `IsolatedFeedRequest` (anonymous, no
  cookies/session/HTMX, validated normalized origin, resolved Site preset) under
  `translation.override(LANGUAGE_CODE)`/`timezone.override(TIME_ZONE)`. Four
  request-local subclasses of the legacy feed classes take the bounded context
  and navigation explicitly and raise instead of building a full repository once
  the context is used; generator mixins append `first`/`next` Atom links (type =
  representation MIME) after all existing root elements, and `feed_url` supplies
  the single canonical `self` including the re-encoded cursor. Serialization
  mirrors `Feed.__call__` without its Last-Modified header. Legacy classes and
  URLs are unchanged. `internal_paged_feed_response` is an explicitly internal,
  `Cache-Control: no-store` adapter (405/400/302/200; HEAD without body) used only
  by test URLconfs (`tests/paged_feed_urls.py`, root and `i18n_patterns` variants);
  it is not the public cache policy. Raised 404s still use Django's handler.
  Tests (`tests/paged_feeds_test.py`): both repository modes and four feed types
  with exact per-GUID item bytes and head metadata parity against the legacy full
  feed (distinct per-episode media and lengths, chapters, transcript), tie-break
  order, empty head and exhausted continuation, page-size change, 404 guards
  preceding cursor handling, generic 400s, restart redirects and key rotation,
  mounts/prefixes/script prefix/origins/canonical re-encoding, fixed locale with
  restored caller language/timezone and unmutated caller request, and bounded
  selection/hydration/rendering. Finding: an episode lacking the requested format
  raises `ValueError` in the legacy full feed in both modes; the adapters keep
  that behavior rather than silently changing membership.
  Implementer: Claude Code Opus 5.5 / medium. Reviewer: Codex GPT-6 Sol / medium,
  one valid round, CLEAN; no skipped or truncated files, only a synthetic test
  signing key redacted. Full independent `just check`: 3,311 passed, five skipped,
  100% coverage; locked Python 3.14 cold-cache mypy and Sphinx `-W` passed.
  The initial full run caught a test-only LocaleMiddleware language leak, repaired
  by restoring the active language around that fixture before review. A transient
  provider/PyPI DNS outage interrupted the first implementation run; a bounded
  fresh Claude session completed it after connectivity returned.
- Step 3 (implemented, independently reviewed; final delta CLEAN):
  `cast.urls` adds the four routes to `paged_feeds.paged_feed_view`. Order: the
  view first marks the request state as paged when the middleware set it; empty
  configuration returns an explicit `no-store` 404 without validators (so
  non-opted-in sites need no middleware); otherwise the view fails
  closed with `ImproperlyConfigured` unless the request carries the state set by
  `cast.middleware.PagedFeedCacheMiddleware` and the pure placement check passes;
  then 405, admission (fresh owner/config/access, canonical path, strict query)
  and `decode_cursor` (the unchanged selection decoder, so signature/scope/version
  handling equals selection) before any cache lookup. A warm hit skips selection
  and hydration. Entries are immutable `(namespace, bytes, content_type, etag,
  generated_at)` tuples under `cast.paged-feeds.v1:<sha256>`; the key digests
  document URL, Site/Blog, scope, record policy incl. page size, repository mode,
  LANGUAGE_CODE, TIME_ZONE and a `salted_hmac` digest of the active SECRET_KEY.
  Entries outside `0 <= age < 300` are deleted and regenerated; hits never call
  set/touch. Weak ETag = sha256 over bytes, document URL, language, timezone.
  The view always returns the complete GET body (also for HEAD and conditional
  requests) as a `no-store` candidate without validators, so inner
  ConditionalGetMiddleware ignores it and Common/GZip middleware produce GET's
  representation headers. The middleware creates request state for every
  request but acts only when the view marked it paged. Its final hook treats
  anything but the view's own 200 candidate object as an uncached `no-store`
  error without validators (raised 404s, 400, 302, 405, replaced responses);
  for the candidate it runs Django's `get_conditional_response` with the entry
  ETag (weak/wildcard If-None-Match → 304 keeping Vary and cookies, plus a
  literal Set-Cookie header; failed If-Match → `no-store` 412; no
  Last-Modified, so IMS alone is ignored while a valid IUS without If-Match
  always fails → 412, and IUS is skipped when If-Match is present).
  Set-Cookie (`response.cookies` or
  a literal header) or Vary outside Accept-Encoding/Accept-Language on the
  candidate or final response yields `private, no-store`, strips validators,
  keeps cookies and the bodyless 304 and evicts a warm key; otherwise it
  applies public headers and inserts cold entries (also after a cold 304) with
  `cache.set(..., 300)`. HEAD bodies are removed last, so HEAD keeps GET's
  Content-Length/Content-Encoding/Vary. Pure checks `cast.E015` (missing, not first or
  duplicated guard, subclasses accepted) and `cast.E016` (Update/Fetch cache
  middleware or subclasses anywhere) import classes only, without DB access.
  Cost: GZip compresses the body of HEAD and 304 responses before it is dropped.
  `internal_paged_feed_response` remains an isolated no-store adapter used only
  by direct-call tests; test URLconfs now mount the real `cast.urls`.
  Tests: `tests/paged_feed_cache_test.py` (+ `tests/paged_feed_middleware.py`)
  and adapted `tests/paged_feeds_test.py`.
  Review round 1 (gpt-6-sol, 2026-09-27) accepted four Warnings, all repaired
  in repair 1: disabled 404 lacked no-store (the view raised before marking
  the route); HEAD built an empty body before Common/GZip (Content-Length 0,
  missing Content-Encoding/Vary); the view's early 304 lost GZip's
  `Vary: Accept-Encoding`; `_is_shared_cache_safe` missed a literal Set-Cookie
  header. Repair tests run the real middleware stack in both GZip/ConditionalGet
  orders (cold/warm, GET/HEAD, fixed GZip padding for header parity, test
  client HEAD body removal disabled), disabled routes with and without the
  middleware, error/redirect HEAD parity and literal Set-Cookie provocations.
  Review round 2 (gpt-6-sol, 2026-09-27) verified the four repairs and raised
  one Warning: the docs claimed IUS → 412 although no Last-Modified is passed.
  Checked against installed Django 6.1 `get_conditional_response`:
  `_if_unmodified_since_passes(None, ...)` is falsy, so IUS without If-Match
  returns 412 (probe: IUS → 412, IMS → 200, matching If-Match + IUS → 200).
  The finding's premise is refuted; docs repair 2 only makes the IUS/If-Match
  interaction explicit in `docs/features/feeds.rst` and here, and notes that
  the weak ETag only passes `If-Match: *`. No runtime change. Regression
  `test_date_preconditions_through_the_full_middleware_stack` runs the real
  middleware stack in both GZip/ConditionalGet orders (IUS past/future → 412,
  unparseable IUS → 200, IMS → 200, `If-Match: *` + IUS → 200, echoed weak
  ETag in If-Match + IUS → 412); Django 5.2 and 6.x share this
  `get_conditional_response` logic.
  Expanded PostgreSQL run (697 tests) had one failure: the deploy/database
  `check` test hit `postgres.E005` because `tests/settings.py` omitted
  `django.contrib.postgres` for Wagtail's search index models. Test settings now
  add it only when `CAST_TEST_DB_ENGINE` is PostgreSQL (SQLite runs unchanged,
  covered by `tests/settings_test.py`). Focused PostgreSQL rerun of
  `tests/feed_pagination_test.py` and `tests/paged_feed_cache_test.py` passes;
  the expanded PostgreSQL run and focused oldest/latest matrix also pass (see step 5).
  Review round 3 verified the documentation/test-settings delta and returned CLEAN.
  All four accepted runtime Warnings are closed; the refuted documentation Warning
  is rejected with source and regression evidence. All rounds used Codex GPT-6 Sol
  at medium effort, with no skipped/truncated files. Only a synthetic test signing
  key was redacted, which does not limit the reviewed behavior. Implementation and
  repairs used Claude Code Opus 5.5 at medium effort. No further review cycle is
  warranted: the gate has converged with no unresolved required findings.
- Step 4 docs (implemented, reviewed with step 3; updated in repair 1): feeds (routes, root/nested
  examples, mandatory middleware, deployment checks, host/port/proxy, cache,
  staleness, CDN path policy, key rotation, disable/rollback, legacy
  recommendation), settings, performance and 0.2.66 release notes.
- Step 5 (locally verified): independent `just check` passes with 3,434 tests,
  five PostgreSQL-only skips and 100% coverage. Locked Python 3.14 cold-cache
  mypy and Sphinx `-W` pass. The focused feed suite passes on Python 3.11 /
  Django 5.2.17 / Wagtail 7.0.9 and Python 3.14 / Django 6.1.1 / Wagtail 8.0
  (557 tests each). A dedicated temporary PostgreSQL 17 instance passes 709
  expanded feed/publication/lock tests plus three Wagtail-V3 PostgreSQL lock tests.
  Existing CI jobs and artifact policy are unchanged; no push or CI run is claimed.
  The complete tox matrix was not run; the approved oldest/latest focused bounds
  and existing PostgreSQL job selections were exercised locally.

## Acceptance matrix and rollout boundaries

Across both repository modes and all four routes: zero/one/N/N+1, tied dates,
deep traversal, unchanging archive exact GUID-set parity, short pages after edits,
at most N hydrated/rendered entries and N+1 lightweight selection, no COUNT/OFFSET
or empty-context full-archive fallback. No constant database scan-work claim.
Include different audio files for each episode and formats with missing media;
preserve the existing serializer's eligibility/enclosure behavior rather than
silently redefining feed membership. Test Podcast-vs-Blog and two-site collisions.

Test canonical links with root/prefixed URL mounts and encoded cursors; strict
query rejection, tamper/unknown-version/wrong-scope recovery, fallback-key signing,
key removal even on warm hits, size-policy changes and independent request state.
Warm-cache tests cover accepted child staleness until expiry, fresh root denial,
config removal before cache, ETag stability/changes on older-entry edits/deletions
after expiry, matching/nonmatching/wildcard If-None-Match and HEAD/304 parity.
Through LocaleMiddleware, ConditionalGetMiddleware and GZipMiddleware, vary
Accept-Language, django_language cookies and active user/session timezones: for
the same URL, XML and ETag must remain identical under fixed settings, with no
caller context mutation. Changing fixed language/timezone settings partitions
the cache and validator even if bytes happen to match. Cover URL-language
prefixes, permitted Vary preservation on 200/304 and private/no-store fallback
for unexpected middleware Vary or Set-Cookie, with no shared-cache reuse.

Ordinary XML/parser fixtures prove serialization and link extraction, not that
installed podcast clients traverse pages. Legacy full URLs stay recommended for
unverified clients. A later separately approved staging/client slice must record
app version, requests and observed archive counts before compatibility claims.
No existing subscription is migrated here. Disabling a record withdraws its paged
URLs (404) but leaves full feeds untouched; this is endpoint withdrawal, not a
transparent rollback for anyone already subscribed to the additive URL. Keep
records/decoders/fallback keys while those subscribers need continuation support.
Changing existing subscription URLs and preserving legacy-family continuation
dispatch remain a separate reviewed migration slice.

## Evidence and review record

Inspected existing feeds, selection, URL/site lookup, settings/check patterns and
installed Django Feed/ConditionalGetMiddleware on 2026-09-21. Source checks of
cast-bootstrap5 and cast-vue show legacy URL/context usage that stays unchanged.
homepage mounts Cast at `/blogs/`; python-podcast mounts it at `/`; both use
USE_TZ=True. Neither consumer is opted in by this work; no sibling edits needed.
No consumer database was accessed and no installed clients were tested.

[RFC 5005 section 3 and appendix B](https://www.rfc-editor.org/rfc/rfc5005.html)
rechecked: next/first navigation and RSS Atom-namespace links support this contract;
the standard explicitly does not promise coherent snapshots. Client evidence in
the original research is historical, not re-certified by this plan.

Historical blocked attempt: the 2026-09-21 isolated Opus/high
harness attempt returned PROVIDER_ERROR before reviewing any content because
Claude Code reported no authenticated session. A prior launch could not write
the shared lock directory; the supported temporary lock directory resolved that
local setup issue, but not authentication. No valid verdict came from that attempt.
On 2026-09-27, restoring session access made Claude authentication available.
First valid review: Opus 5.5 / medium, one Warning about request-derived locale
and shared HTTP caches. Accepted: explicitly fix language/timezone to Django
settings, include them in cache/validator identity, enumerate safe Vary headers,
and add full-middleware acceptance tests. Round 2 confirmed this repair and
raised one directly coupled Warning: final Set-Cookie/Vary handling needs an
explicit outermost response hook. Accepted: specify opt-in-required first-position
middleware, deferred cache insertion and identical final checks for 200/304,
hits/misses. Another delta review is required because this repair adds a concrete
middleware-ordering contract rather than just rewording the original locale rule.
Round 3 independently verified the repair: no Critical/Warning remained, two
Suggestions. Accepted both as contract clarifications: a cold 304 may populate
the cache with its complete safe 200 candidate, and pure checks reject Django's
full-site cache middleware instead of promising an unspecified bypass. Stop at
advisory convergence; no further agreement-seeking round is needed. This is not
a CLEAN verdict and does not certify a future implementation.
All three valid rounds used claude-opus-5-5 at medium effort, with no skipped,
truncated or redacted evidence and no reviewer subagents. Current artifacts:
`/tmp/cast-endpoint-review.hmSrPg/round1/` through `round3/` (ephemeral).
Artifacts: `/tmp/cast-feed-endpoints.oxsakp/review2/` (ephemeral).
Implementation approval: pending at review time; granted 2026-09-27 (see Status). No runtime changes, commits or pushes in this
review turn; the earlier draft was already committed as 8dc43197.

Historical validation: `git diff --check`, lint and mypy passed. `just check` with a
temporary writable uv cache and the existing environment reached 3,093 passing
tests and five skips; one packaging test failed because the restricted session
could not resolve pypi.org to fetch uv-build. The full check is therefore NOT
green in that session. No runtime
test failure was diagnosed and no test was disabled or weakened.

Historical plan-review validation (2026-09-27): `just check` passed, including lint, mypy,
3,094 tests, five skips and 100% coverage. The earlier packaging dependency-fetch
blocker is resolved. Later changes in this review are planning prose only;
`git diff --check` passed. That pre-implementation record is superseded by the
implementation validation above; release notes now describe the shipped endpoints.

Workflow lesson: an installed review CLI and historical successful reviews do
not establish that the current restricted session can authenticate. Verify a
valid verdict rather than treating a provider failure as absence of findings.
Promotion: incident — the existing fail-closed review rule already covers this;
recorded here because the shared external workflow log is not writable.
