# Paged feeds: deferred

Status: decision record, 2026-09-28. Paged feeds are withdrawn from `develop` and
parked on the `archive/paged-feeds` branch (tip `c20d6d80`). The earlier
[research](2026-09-19-paged-feeds.md), [spike](2026-09-19-paged-feeds-slice1.md),
[selection](2026-09-19-paged-feeds-selection.md) and
[endpoint](2026-09-21-paged-feeds-endpoints.md) notes are historical.

## What was built

- Signed keyset selection service (`cast.feed_selection`).
- `CAST_FEED_PAGINATION` setting, strict Site/Blog owner resolution and system checks E011–E016.
- Request-isolated paged RSS/Atom serializers with RFC 5005 `first`/`next` links.
- Four opt-in routes with a dedicated 300-second response cache, weak ETags and a mandatory
  outermost `PagedFeedCacheMiddleware`.

Roughly 1,200 lines of runtime code and 2,000 lines of tests. Migration
`0083_post_feed_boundary_index` stays on `develop` because it was already pushed and the
index also serves the date-ordered full feeds.

## Why it was deferred

Measured on the Django Chat staging feed (206 episodes) on 2026-09-28:

| | Staging (django-cast) | Simplecast (production) |
|---|---|---|
| Raw size | 1.14 MB | 726 KB |
| gzip / brotli | 108 KB / 86 KB | 106 KB (gzip) |
| Conditional GET | none: `If-Modified-Since` always returned 200 | ETag and Last-Modified, 304 |
| Cache-Control | `max-age=300` | `max-age=3600` |

- A cold render took about 0.7 s and happens at most once per cache period. Cache hits
  needed no database queries, so per-request database load was not the problem.
- `itunes:summary` duplicated `description` and accounted for about 36% of the raw feed.
- A 100-item first page would be 59 KB gzip instead of 108 KB. A 304 saves the whole body.

Client research (2026-09-28): only AntennaPod (manual "load more"), gPodder and Podcast
Addict follow `rel="next"`. Pocket Casts is unclear. Apple Podcasts, Spotify, YouTube Music,
Amazon, Overcast and Castro have no documented support, so for them a paged feed behaves
like a feed truncated to its first page. Podlove Publisher still offers paging, but its own
showcase feed serves the full archive. Major hosts (Libsyn, Buzzsprout, Simplecast) offer
episode limits, not paging. Apple and Spotify use conditional GET; Apple did not request
compression in published logs, so raw size matters for changed feeds. Sources:
<https://github.com/Podcastindex-org/podcast-namespace/issues/117>,
<https://podlove.org/blog/paged-feeds-for-podcasts/>,
<https://www.earth.org.uk/RSS-efficiency.html>, <https://podnews.net/article/rss-tests>.

## What replaced it

Legacy feeds send ETags and answer conditional requests with 304, and `itunes:summary`
became optional (see the 0.2.66 release notes).

## When to revisit

Reconsider paging only if a major client (Apple, Spotify, Overcast, Pocket Casts) documents
RFC 5005 support, or if a site's feed stays too large after conditional GET, compression and
payload trimming. Rebasing the archive branch will need work in `feeds.py`, `checks.py` and
`urls.py`.
