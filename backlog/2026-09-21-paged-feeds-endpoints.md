# Paged feeds: additive HTTP endpoint contract

Status: draft for independent review and maintainer approval. Planning only;
no endpoints, settings or subscription changes have been implemented here.
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
effective normalized policy including page size, repository mode, language and
timezone. Include the active signing-key generation via a one-way digest so key
rotation cannot reuse cached next links signed by a removed key; never log keys.
Version the namespace when serialized semantics change across deployments.

Render with an isolated anonymous public request: no credentials, caller user,
session theme overrides or HTMX state may influence shared XML. Retain only the
validated origin, path and resolved Site; use the site's theme and active language
and timezone (included in cache identity). Do not mutate the caller request.
Do not store responses with Set-Cookie or unexpected Vary headers. Built-in
rendering must be shown deterministic across logged-in/anonymous requests; custom
templates are responsible for not depending on other unkeyed request inputs.

On 200, send `Cache-Control: public, max-age=300` and an Age reflecting time since
representation generation (not since this hit); do not reset downstream freshness
on every hit or on 304. Expired entries are regenerated, not served stale on errors.
Child deletion/restriction/unpublish/edit/media changes may remain visible in a
warm representation for that window. No immediate revocation claim. Fresh root
checks apply to requests reaching Django; browser/CDN caches cannot perform them.
Full-site cache middleware/CDNs must not bypass these guards at the origin or
extend this freshness window; document the required path exclusions/configuration.

Remove Django Feed.__call__'s item-date Last-Modified header on these new routes
only: a newest-item timestamp misses changes to older entries. Use a weak ETag
derived from the serialized bytes and canonical document URL, not max publication
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
3. Add the bounded response cache and conditional handling above; test complete
   middleware paths, cache partitioning and anonymous rendering isolation.
4. Update feed/settings/performance docs and current release notes, with opt-in,
   post-migration checks, key rotation, limitations and disable/rollback examples.
   Update this plan and BACKLOG to reflect implementation, not just test success.
5. Run just check (100%), locked Python 3.14 cold-cache mypy, Sphinx -W, focused
   oldest/latest dependency checks and existing PostgreSQL selection job. Reuse
   jobs; no additional Actions service, benchmark job or artifact uploads.
   Independently review code before any later commit request.

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

Independent review: blocked, not passed. The 2026-09-21 isolated Opus/high
harness attempt returned PROVIDER_ERROR before reviewing any content because
Claude Code reported no authenticated session. A prior launch could not write
the shared lock directory; the supported temporary lock directory resolved that
local setup issue, but not authentication. No valid review round or verdict
exists. Resume the same draft through the review harness after authentication
is available, adjudicate findings, then seek implementation approval.
Artifacts: `/tmp/cast-feed-endpoints.oxsakp/review2/` (ephemeral).
Implementation approval: pending. No source changes, commits or pushes.

Local validation: `git diff --check`, lint and mypy pass. `just check` with a
temporary writable uv cache and the existing environment reached 3,093 passing
tests and five skips; one packaging test failed because the restricted session
could not resolve pypi.org to fetch uv-build. The full check is therefore NOT
green; rerun in an environment with the build dependency available. No runtime
test failure was diagnosed and no test was disabled or weakened.

Workflow lesson: an installed review CLI and historical successful reviews do
not establish that the current restricted session can authenticate. Verify a
valid verdict rather than treating a provider failure as absence of findings.
Promotion: incident — the existing fail-closed review rule already covers this;
recorded here because the shared external workflow log is not writable.
