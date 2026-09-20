# Rejected proposal: full-feed cache repair

Status: REJECTED / historical. The user explicitly accepts five-minute staleness
as expected caching, not a bug. No repair or immediate-revocation requirement
remains. The recommendation below records the rejected proposal, not current policy.
Scope: existing blog/podcast RSS and Atom routes, both repositories, all supported
audio formats. Independent implementation review required before landing.

## Evidence

- `src/cast/urls.py` wraps each XML view in a five-minute `cache_page`, inside
  `unrestricted_page_required(Blog)`. Root access is checked on origin requests;
  cached XML bypasses child selection and rendering.
- Both repository branches freshly select live/public descendants on a cache
  miss; the default branch's "cachable data" is not itself a persistent feed
  cache. No feed invalidation receivers were found in the application.
- All 32 baseline tests pass again. They reproduce stale child XML after delete,
  unpublish or direct restriction, and exclusion after clearing the cache.
  Existing tests separately prove root restrictions block a warm origin cache.
- Django's installed syndication view sets Last-Modified from latest_post_date;
  Cast supplies visible_date and last_published_at. These dates are not a feed
  revision: deleting/restricting an older item can leave the maximum unchanged.
  ConditionalGetMiddleware can consequently return 304 for changed membership.
  This is source-derived risk, not yet an end-to-end regression reproduction.
- Local consumer production settings both use file-based caches. Homepage's
  site-wide cache middleware is commented out. Neither observation establishes
  actual deployed proxy/CDN configuration; that needs deployment verification.

## Recommended first repair: fresh origin responses

1. Remove the four built-in XML response-cache wrappers. Retain current public
   root checks and fresh child filtering. No schema migration, Redis dependency,
   new settings or public opt-out that silently restores stale permission checks.
2. Return Cache-Control `private, no-store, no-cache, max-age=0, must-revalidate`
   and an expired Expires header. Apply the policy to successful feed responses,
   denied/not-found feed responses and method/error handling owned by these
   endpoints. Ordinary raised Http404 bypasses a response decorator: implementation
   must explicitly cover that path without changing the site's custom error
   rendering. Server-wide exception/proxy behavior remains deployment-owned.
3. Strip ETag and Last-Modified HTTP headers. Do not alter XML publication dates,
   GUIDs, self links, enclosures or feed identities. Conditional requests receive
   fresh 200 XML or the current error, not 304. Django's standard conditional
   middleware skips generating ETags for no-store, but still consumes an existing
   Last-Modified header, so both parts are necessary.
4. Guarantee fresh database visibility for requests beginning after a committed
   mutation, under the normal non-lagging database read configuration. Do not
   promise cancellation of in-flight responses or atomic snapshots spanning
   multiple queries. Replicas with lag weaken this guarantee and must not serve
   access-sensitive feed reads under a stronger advertised contract.
5. This repairs feed output, not recall of public information: podcast clients
   may retain downloaded episodes. Media URLs/storage ACLs and independent media
   caches are a separate policy, not automatically revoked by hiding an item.

## Why this choice, and its cost

Shortening the TTL only shortens the exposure window. Cache deletion on publish
alone misses restrictions, ancestor changes, moves, deletes and non-editor paths.
Even broad signal deletion needs cross-worker semantics and race protection:
an in-flight old render can refill the cache after invalidation. An on_commit
callback is appropriate timing but not an atomic cross-system generation protocol.

A per-request eligible-ID check could preserve warm XML while excluding revoked
items. It still scans the archive, must bind the exact rendered membership to its
cache entry, and does not detect sensitive text edits, metadata changes or related
media updates. It is a possible separately scoped optimization, not a complete
freshness repair. A database generation scheme is also viable future work, but
requires a comprehensive mutation contract and transaction/race tests.

The recommended repair trades performance for a small, auditable correctness
boundary. In the [disposable spike](2026-09-19-paged-feeds-slice1.md), 10k empty-body
posts took roughly 11–13 seconds to render cold versus about 0.07 seconds warm
in django mode (instrumented samples, not production SLA estimates). Every request
would now pay rendering cost; full XML remains roughly 8.5 MB. This is material
for large/busy feeds and must be explicitly accepted before implementation/deploy.
No default truncation or subscription migration is proposed as a shortcut.
Paged opt-in endpoints subsequently bound rendering; they do not solve load from
clients that continue using full feeds. If this cost is unacceptable, investigate
a validated render cache before deploying the repair, rather than claiming the
current cache is safe.

## Deployment and rollback

Drain/restart all old application workers so no old cache-serving code remains.
New code must not read old XML cache keys; leave unrelated application caches
alone. Purge only matching feed paths/variants at any configured reverse proxy or
CDN, and exclude these routes from site-wide response caching. Old downstream
responses can remain fresh until their previous TTL expires; new no-store headers
cannot retroactively remove them. Verify origin AND public-edge responses.
Local sibling settings are inspection evidence, not a production rollout audit.

Do not advertise rollback to old caching as safe. A rollback restores the known
stale-child window; it requires explicit operator acceptance and cache/edge checks.

## Acceptance for an approved implementation

- Replace stale-child characterization assertions with immediate exclusion on
  all four routes and both repositories; keep membership/identity regressions.
- Cover direct/inherited restrictions, unpublish, delete, moves out of the feed,
  republish/restriction removal, content edits and removal of podcast audio.
- Recheck root restrictions and their removal, including error response headers.
- Test If-Modified-Since for deletion of an older item with unchanged latest date,
  If-None-Match (including wildcard), and combined headers through real Django
  ConditionalGetMiddleware. No stale 304, no HTTP validators, GET/HEAD agree.
- Exercise standard cache middleware with pre-existing cached responses and
  document the required deployment purge; view headers cannot bypass an upstream
  cache hit. Ensure subsequent responses are not stored by standard middleware.
- Test distinct instances/workers using the same configured cache and ensure no
  feed cache reuse; no process-local invalidation assumptions.
- Keep runtime URLs and configuration unchanged; update feeds/performance docs,
  current release notes, backlog and affected baseline tests together.
- Run focused tests, `just check` (100% coverage), docs build and independent
  review. No new benchmark CI job or external database service required.

## References

- [Django caching](https://docs.djangoproject.com/en/5.2/topics/cache/): per-view,
  per-process and downstream cache distinctions.
- [Django conditional middleware](https://docs.djangoproject.com/en/5.2/ref/middleware/#conditional-get-middleware):
  validator-based conditional responses; installed implementation inspected too.
- [Django transaction callbacks](https://docs.djangoproject.com/en/5.2/topics/db/transactions/#performing-actions-after-commit):
  callbacks run after commit, not as part of the committed transaction.
- [RFC 9111, no-store](https://www.rfc-editor.org/rfc/rfc9111.html#name-no-store-2):
  cache storage prohibition is not a guarantee of privacy or client-side recall.
