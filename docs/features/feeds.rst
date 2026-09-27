.. _feeds_overview:

*****
Feeds
*****

Django Cast provides comprehensive feed support for both blogs and podcasts, with RSS and Atom formats, iTunes metadata, and performance optimizations.

Feed Detail Page
================

Each blog and podcast has a dedicated feed detail page at ``<slug>/feed/``
(URL name ``cast:feed_detail``) that lists all available feeds in one place:

- **Blog RSS and Atom feed** links (for all blogs)
- **Platform links** — Apple Podcasts, Spotify, YouTube (for podcasts, when the
  corresponding key is set in ``CAST_FOLLOW_LINKS``)
- **Podcast feeds** table with all four audio formats (MP3, M4A, OGA, OPUS) in
  both RSS and Atom (for podcasts only)

The navbar RSS icon links to this page instead of the raw XML feed. Custom
themes without a ``feed_detail.html`` template automatically fall back to the
plain theme.

Feed XML endpoints use shared response caches, and the feed detail page is also
public. These endpoints are available only for live blogs and podcasts without
Wagtail login, password, or group restrictions on the page or any ancestor.
Restricted pages return 404; django-cast does not expose authenticated private
feeds.

The template receives the following context variables:

- ``blog`` — the Blog or Podcast instance
- ``is_podcast`` — boolean, ``True`` for podcasts
- ``blog_feed_url`` — URL to the blog RSS XML feed
- ``blog_atom_feed_url`` — URL to the blog Atom XML feed
- ``template_base_dir`` — the active theme name
- ``podcast_feeds`` — list of dicts with ``format``, ``format_label``,
  ``rss_url``, ``atom_url`` (podcasts only)
- ``apple_podcasts_url`` — Apple Podcasts URL from settings, or ``None``
  (podcasts only)
- ``spotify_url`` — Spotify URL from settings, or ``None`` (podcasts only)
- ``youtube_url`` — YouTube URL from settings, or ``None`` (podcasts only)

Feed Types
==========

Blog Feeds
----------

Blog feeds are available in RSS and Atom formats, automatically generated from your blog content:

- RSS 2.0 feed at ``<slug>/feed/rss.xml``
- Atom 1.0 feed at ``<slug>/feed/atom.xml``
- Feed fields populated from Blog model: title, description, author
- Automatic inclusion of post content (overview and detail sections)

Blog RSS item GUIDs are based on the post UUID with ``isPermaLink="false"``, so
they are stable across slug and URL changes. Feed readers that subscribed before
UUID-based GUIDs were introduced see each existing post once as new; from then on
the GUIDs remain constant.

Podcast Feeds
-------------

Podcast feeds extend blog feeds with additional podcast-specific features:

- iTunes podcast metadata (artwork, categories, explicit content marking)
- Optional episode publishing metadata for iTunes and Podcasting 2.0:
  episode number, episode type, and season
- Audio file enclosures for episode distribution
- Multiple audio format support with separate feeds per format
- RSS at ``<slug>/feed/podcast/<audio_format>/rss.xml``
- Atom at ``<slug>/feed/podcast/<audio_format>/atom.xml``
- Chapter marks support for enhanced navigation
- Transcript URLs included in feeds (WebVTT and DOTE formats)

Feed Fields
===========

Standard Fields
---------------

These fields are populated from the Blog/Podcast model:

- **Title**: From the blog's title field
- **Description**: From the blog's description field
- **Author**: Populates both iTunes and Atom feed author tags
- **Link**: Canonical URL to the blog/podcast homepage
- **Language**: Configurable per blog instance

Podcast-Specific Fields
-----------------------

Additional metadata for podcast feeds:

- **iTunes Artwork**: High-resolution podcast cover image
- **iTunes Subtitle**: From the blog's subtitle field
- **iTunes Categories**: Podcast directory categorization
- **Explicit Content**: Content rating flag
- **Podcast Type**: Optional ``episodic`` or ``serial`` channel ordering value
  emitted as ``itunes:type`` only when explicitly configured.
- **Episode Enclosures**: Audio files with proper MIME types
- **Episode Duration**: Calculated from audio files
- **Episode Number**: Optional positive integer emitted as ``itunes:episode``
  and ``podcast:episode``
- **Episode Type**: Optional ``full``, ``trailer``, or ``bonus`` value emitted
  as ``itunes:episodeType`` only when explicitly set; a blank value omits the
  tag and is equivalent to ``full``
- **Season**: Optional reusable season object scoped to the podcast. Positive
  season numbers are emitted as ``itunes:season`` and ``podcast:season``; a
  season name is emitted as the Podcasting 2.0 ``name`` attribute.
- **Chapter Marks**: Time-indexed navigation points
- **Transcripts**: Links to VTT and DOTE transcript files

Podlove Simple Chapters
~~~~~~~~~~~~~~~~~~~~~~~

Podcast RSS and Atom feeds include inline Podlove Simple Chapters for episodes
that have chapter marks. The ``psc`` namespace is declared on each emitted
``psc:chapters`` element, not on the feed root, so feeds and episodes without
chapter marks remain unchanged.

The emitted shape is::

    <psc:chapters version="1.2" xmlns:psc="http://podlove.org/simple-chapters">
      <psc:chapter start="00:01:23" title="Intro"/>
      <psc:chapter start="00:04:56.789" title="Topic"/>
    </psc:chapters>

(The feed serializer emits self-closing empty elements and sorts element
attributes alphabetically.)

Chapter ``start`` values use ``HH:MM:SS`` or ``HH:MM:SS.mmm`` when fractional
seconds are present. Podlove Simple Chapters v1 output currently includes the
``start`` and ``title`` attributes only.

Chaptered episodes also include a Podcasting 2.0 external chapters reference::

    <podcast:chapters type="application/json+chapters" url="https://example.com/chapters/<audio pk>/?episode_id=<episode pk>"/>

The stable endpoint path is ``chapters/<audio pk>/?episode_id=<episode pk>``.
``application/json+chapters`` is the Podcasting 2.0 specification's literal media-type
string, not ``application/chapters+json``.
It returns ``application/json+chapters`` with this body shape::

    {
      "version": "1.2.0",
      "chapters": [
        {"startTime": 83, "title": "Intro"}
      ]
    }

``startTime`` values are integer seconds. Access to the endpoint uses the same
audio-access checks as public audio and transcript endpoints: the supplied
``episode_id`` must reference the audio and be viewable by the requester.
Denied requests raise ``Http404`` so object existence is not leaked. Authorized
requests for audio without chapter marks return a valid empty chapters document.

RSS item GUIDs remain based on the episode UUID with
``isPermaLink="false"``. Episode numbers, episode types, and seasons are
publishing metadata only; changing them does not change feed identity.

Backfilling Podcast Metadata
----------------------------

Existing podcasts do not need a data migration. The new episode number,
episode type, and season fields are optional and feeds omit the corresponding
tags until values are set.

When backfilling from imported source metadata, copy only values that are valid
for the django-cast fields: positive integer episode numbers, positive integer
season numbers, and one of ``full``, ``trailer``, or ``bonus`` for episode
type. Leave legacy values such as ``0``, blank numbers, decimal episode numbers,
or host-specific display labels unset until a project-specific mapping is
chosen. Keep imported GUIDs or django-cast UUIDs as feed identity; do not derive
identity from episode or season numbers.

Feed Generation
===============

Repository Pattern
------------------

Feeds use the FeedContext pattern for optimized generation:

.. code-block:: python

    # Efficient feed generation with minimal queries
    repository = FeedContext(blog)
    # All posts and related data prefetched

Performance Features
--------------------

- **Feed Caching**: Generated XML cached to reduce server load
- **Prefetch Optimization**: Single query retrieves all feed data
- **Lazy Loading**: Large content fields loaded on-demand
- **Conditional GET**: Support for If-Modified-Since headers

Host and Site Configuration
---------------------------

Feed self URLs and relative channel links use the request host validated by
Django's ``ALLOWED_HOSTS``, which supports sites served from more than one
configured hostname. Cached feed responses are scoped to that host. Item URLs
continue to follow Wagtail site routing. Feed rendering does not replace
Django's process-wide current ``Site`` with request data. When
``django.contrib.sites`` is installed, ``SITE_ID`` must identify an existing
``django_site`` row (or, without ``SITE_ID``, the request host must match one);
otherwise feed generation raises an explicit configuration error. Without the
Sites app, Django's request-local ``RequestSite`` fallback is preserved.

API Access
==========

Feeds are also available via the REST API:

- ``/api/posts/`` - JSON feed of blog posts
- ``/api/episodes/`` - JSON feed of podcast episodes
- Supports filtering, pagination, and field selection
- Machine-readable alternative to XML feeds

Configuration
=============

.. _paged_feeds:

Paged feeds (opt-in)
--------------------

Paged feeds are additive, opt-in RSS/Atom endpoints that serve an archive in
bounded pages linked with RFC 5005 ``next`` links. They are disabled by default
(``CAST_FEED_PAGINATION = []``). The existing full feeds, their URLs, feed-detail
links, autodiscovery and five-minute caching are unchanged and remain the
default. **Keep recommending the full feeds for podcast apps and readers you
have not verified yourself:** django-cast makes no claim that any particular
client follows ``next`` links, and paging-unaware clients only see the first page.

Four routes are added beneath the existing ``cast.urls`` mount:

.. list-table::
   :header-rows: 1

   * - Relative route
     - URL name
   * - ``<slug>/feed/paged/rss.xml``
     - ``cast:paged_entries_feed``
   * - ``<slug>/feed/paged/atom.xml``
     - ``cast:paged_entries_atom_feed``
   * - ``<slug>/feed/podcast/<audio_format>/paged/rss.xml``
     - ``cast:paged_podcast_feed_rss``
   * - ``<slug>/feed/podcast/<audio_format>/paged/atom.xml``
     - ``cast:paged_podcast_feed_atom``

With Cast mounted at ``/blogs/`` a nested Blog ``podcast`` serves
``/blogs/podcast/feed/podcast/mp3/paged/rss.xml``; with Cast mounted at ``/`` it
is ``/podcast/feed/podcast/mp3/paged/rss.xml``. URL language prefixes from
``i18n_patterns`` are kept in the document URL. Always reverse the URL names
instead of hard-coding paths. A Podcast record enables both blog feeds and the
podcast feeds in every supported audio format; a plain Blog only the two blog feeds.

Selection loads IDs and dates before either repository hydrates media, using
signed continuation cursors and stable date/ID ordering. It requires
``USE_TZ=True`` so UTC cursors round-trip timestamps without ambiguity.

Enabling paged feeds
~~~~~~~~~~~~~~~~~~~~

The setting is a ``list`` of records; each record is a ``dict`` with required
``hostname``, ``port`` and ``blog_path`` and an optional ``page_size`` (default
``100``). Tuples, other mappings, unknown fields, duplicate targets and
booleans used as integers are rejected:

- ``hostname`` is a bare ASCII host (no scheme, port or path). Case and one
  trailing dot are normalized; IPv6 literals use brackets.
- ``port`` is an integer from 1 to 65535 and must match the Wagtail ``Site``.
- ``blog_path`` is the Blog's page path relative to the ``Site`` root page,
  with leading and trailing slashes: ``"/"`` for a Blog that is the site root,
  ``"/blog/"`` for a nested one. It is not a feed URL; queries, fragments,
  percent escapes and empty or dot segments are rejected.
- ``page_size`` is an integer from 1 to 500.

.. code-block:: python

    CAST_FEED_PAGINATION = [
        {"hostname": "example.com", "port": 443, "blog_path": "/"},
        {"hostname": "example.com", "port": 443, "blog_path": "/podcast/", "page_size": 50},
    ]

The first record enables a Blog that is the Site root page, the second a nested
Podcast. Paged feeds also require the finalizing middleware as the **first**
``MIDDLEWARE`` entry, and Django's full-site cache middleware must be removed:

.. code-block:: python

    MIDDLEWARE = [
        "cast.middleware.PagedFeedCacheMiddleware",  # must be first
        "django.middleware.gzip.GZipMiddleware",
        "django.middleware.http.ConditionalGetMiddleware",
        "django.middleware.security.SecurityMiddleware",
        "django.contrib.sessions.middleware.SessionMiddleware",
        # ... the rest of your middleware, without UpdateCacheMiddleware,
        # FetchFromCacheMiddleware or CacheMiddleware (or subclasses)
    ]

The middleware is transparent for every request except the four paged routes.
Its response hook runs after session, CSRF, locale, conditional-GET and
compression middleware, so it sees the final headers. The paged view always
returns the complete ``GET`` representation, also for ``HEAD`` and conditional
requests, so other middleware (for example ``CommonMiddleware`` and
``GZipMiddleware``) produce the same representation headers for every request;
the hook then evaluates preconditions and removes ``HEAD`` bodies. There is no setting to
bypass either requirement. If a paged route is requested while pagination is
configured but the middleware is missing or misplaced, the request fails with
``ImproperlyConfigured`` instead of serving an unguarded response.

Deployment steps:

1. Upgrade and run ``python manage.py migrate``.
2. Add the records and the middleware, then run ``python manage.py check``
   (pure checks) and ``python manage.py check --deploy --database default``
   (database-backed target resolution) before routing traffic.
3. Request the paged head through your real host, port and proxy and confirm
   ``200``, ``Cache-Control: public, max-age=300`` and the expected ``self`` URL.

A record resolves only to the ``Site`` with exactly that hostname and port;
Wagtail's default-site fallback never applies. The page at ``blog_path`` under
that site root (inclusive) must be a Blog or Podcast. Its slug must be unique
among Blog and Podcast pages on the site, including drafts, because feed routes
are addressed by slug. Requests must use the configured host, validated by
``ALLOWED_HOSTS``; an omitted port follows the request scheme. Forwarded host
and scheme headers count only through Django's ``USE_X_FORWARDED_HOST`` and
``SECURE_PROXY_SSL_HEADER``. Owners are rechecked for live, unrestricted
public access (including inherited view restrictions) on every resolution.
Only the configured exact hostname and port are served: other aliases of the
Site return 404 even if Wagtail would route them, unlike the full feeds. The
record's port, the Wagtail Site port and the effective request port must all
agree: behind a TLS-terminating proxy that forwards ``https`` on port 443,
configure ``"port": 443``, a Site with port 443 and a trusted
``SECURE_PROXY_SSL_HEADER``, and make the proxy pass the original ``Host``
header. Renames and moves require updating the record; old paged URLs are not
redirected automatically.

System checks for this setting:

- ``cast.E011``: malformed ``CAST_FEED_PAGINATION``. Fix the reported entry.
- ``cast.E012``: records are configured while ``USE_TZ`` is disabled. Enable
  ``USE_TZ`` or remove the records.
- ``cast.E013``: a record does not resolve to exactly one Site and Blog, or its
  slug is ambiguous on that Site. Update the hostname, port or path after
  renames and moves, or make the slug unique.
- ``cast.E014``: target resolution could not read the database. Run
  ``migrate`` first.
- ``cast.E015``: ``cast.middleware.PagedFeedCacheMiddleware`` is missing, not
  the first ``MIDDLEWARE`` entry, or listed more than once. Move it to the top.
- ``cast.E016``: Django's ``UpdateCacheMiddleware``,
  ``FetchFromCacheMiddleware`` or ``CacheMiddleware`` (or a subclass) is in
  ``MIDDLEWARE``. Remove it; paged feeds cache their own responses and other
  views need endpoint-specific caching.

``cast.E011``, ``cast.E012``, ``cast.E015`` and ``cast.E016`` run in every
``check`` without database access (``E015``/``E016`` only when records are
configured). ``cast.E013`` and ``cast.E014`` query the database, so they run only
with ``python manage.py check --deploy --database default`` after migrations,
never during ordinary checks, ``migrate`` or ``check --tag cast``.

Requests and pages
~~~~~~~~~~~~~~~~~~

Only ``GET`` and ``HEAD`` are allowed (other methods get ``405``). A request is
admitted only for a configured, live and public owner (otherwise ``404``); the
query must be empty or exactly one nonempty ``cursor`` (raw query bounded to
4096 bytes, strict percent escapes), otherwise ``400``. A cursor with a
signature that no current or fallback key verifies, or an unsupported version,
redirects (``302``) to the paged head. At most ``page_size + 1`` lightweight rows
are selected and only the page is hydrated.
Each page is serialized by request-local subclasses of the existing RSS, Atom
and podcast feed classes, so item GUIDs, links, content, dates, enclosures,
iTunes/Podcasting 2.0 elements, chapters, transcripts, stylesheets and Atom feed
IDs match the full feed. An episode missing the requested audio format fails
exactly as it does in the full feed. Pages carry one ``self``, a ``first`` link
to the bare paged head and ``next`` only when more entries follow, as Atom links
with the representation MIME type (inside the RSS channel for RSS).
Rendering uses an anonymous request with the validated origin and resolved Site
only, ``settings.LANGUAGE_CODE`` and ``settings.TIME_ZONE``; caller cookies,
session themes, users and HTMX headers are ignored and the caller's active
language and timezone are restored. Custom feed templates must not depend on
other request inputs, because the XML is shared between all callers.
Pages are mutable views, not snapshots: concurrent edits can shorten pages or
cause repeats or omissions while a client walks the archive.

Caching and HTTP validators
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Successful pages are cached for 300 seconds in Django's ``default`` cache,
under a versioned namespace separate from the full feeds. The key covers the
canonical document URL (scheme, host, port, mount, cursor), Site and Blog,
feed kind/format/representation, page size, repository mode, the fixed
language and timezone, and a one-way digest of the active signing key. Hits
never renew the entry. Responses carry ``Cache-Control: public, max-age=300``,
an ``Age`` counted from generation, and a weak ``ETag`` derived from the XML
bytes, the document URL and the fixed language/timezone. There is deliberately
no ``Last-Modified``: the newest item date misses edits to older entries.
``If-None-Match`` (including ``*``) on ``GET``/``HEAD`` returns a bodyless
``304``; ``If-Modified-Since`` alone returns the normal page. Preconditions are
evaluated by the finalizing middleware after compression, in either order of
``GZipMiddleware`` and ``ConditionalGetMiddleware``, so a ``304`` keeps the
``Vary`` headers of the ``200`` (``Accept-Encoding``, ``Accept-Language``) as
well as its ``ETag``, ``Cache-Control`` and ``Age``. A failed ``If-Match``
returns an uncached ``412``; ``If-Match`` uses strong comparison, so only
``If-Match: *`` passes against the weak ``ETag``. Because there is no ``Last-Modified``, a valid
``If-Unmodified-Since`` sent without ``If-Match`` can never pass and also
returns ``412``; when ``If-Match`` is present, ``If-Unmodified-Since`` is not
evaluated. ``HEAD`` responses carry
the ``GET`` headers, including ``Content-Length``, ``Content-Encoding`` and
``Vary``, without a body. As a consequence, compression runs for every
successful request, including ``HEAD`` and ``304`` responses, before the body is
discarded.

Accepted staleness: deleting, restricting, unpublishing or editing a *child*
entry, or changing its media, can stay visible in a cached page for up to five
minutes; there is no immediate revocation. The Blog itself, its configuration,
and the cursor (including signature) are checked freshly on every request that
reaches Django, before the cache is consulted. Browser and CDN caches cannot
perform these checks.

Errors, redirects and ``405`` responses are never cached and carry
``Cache-Control: no-store`` without validators. If other middleware adds
``Set-Cookie`` (through ``response.cookies`` or as a literal header) or a
``Vary`` header other than ``Accept-Encoding`` or
``Accept-Language`` (for example ``Vary: Cookie`` after session access), the
``200``/``304`` becomes ``Cache-Control: private, no-store`` without validators,
keeps its cookies, is not stored, and an existing cache entry is evicted.

CDN and proxy policy: a CDN in front of these paths must honor the origin's
``Cache-Control``/``Age`` and must not extend freshness beyond five minutes,
ignore ``no-store``/``private``, or answer requests without forwarding the
query string. If your CDN cannot guarantee that, exclude the
``*/feed/paged/*`` and ``*/feed/podcast/*/paged/*`` paths from CDN caching.

Key rotation: continuation links are signed with ``SECRET_KEY``. When rotating,
move the old key to ``SECRET_KEY_FALLBACKS`` so existing links keep working;
rotation also starts a new cache partition, so no cached page offers links
signed by an old key. Removing a key from the fallbacks makes its links restart
at the paged head, even for pages that are still cached.

Disabling and rollback: removing a record (or clearing the setting) makes its
paged URLs return ``404`` immediately; the full feeds are untouched. With the
setting empty the middleware is optional, and the ``404`` is ``no-store``
without validators either way. This
withdraws the endpoints; it is not a transparent rollback for anyone who
already subscribed to a paged URL. Keep records, cursor decoding and fallback
keys while such subscribers need continuation support. Existing subscriptions
are not migrated to paged URLs by django-cast.

Migration ``0083_post_feed_boundary_index`` adds a composite post date/ID index.
Run the normal ``migrate`` command after upgrading. Creating the index can lock
the post table; schedule the migration appropriately for large installations.

Feed Limits
-----------

The full feeds include all eligible live, publicly accessible entries; there
is no configurable item limit. Use the opt-in :ref:`paged feeds <paged_feeds>`
for bounded pages. ``CAST_FEED_ITEM_LIMIT`` is not
implemented and setting it has no effect. Podcast feeds additionally require
podcast audio.

Follow Links
------------

Configure platform links shown on the feed detail page for podcasts:

.. code-block:: python

    CAST_FOLLOW_LINKS = {
        "apple_podcasts": "https://podcasts.apple.com/...",
        "spotify": "https://open.spotify.com/show/...",
        "youtube": "https://www.youtube.com/@...",
    }

Cache Duration
--------------

The built-in XML feed routes cache responses for five minutes.
``CAST_FEED_CACHE_TIMEOUT`` is not implemented and setting it has no effect.
The feed root's public accessibility is rechecked before serving cached output.
Changes to individual entries (including removal or new view restrictions) can
remain in a warm response until it expires or is invalidated. When restricting
previously public content, account for application and downstream caches; a
cached feed is not an immediate-revocation mechanism.

Best Practices
==============

1. **Use Descriptive Titles**: Feed titles should clearly identify your content
2. **Set Appropriate Descriptions**: Descriptions appear in feed readers
3. **Configure Author Information**: Improves attribution and discoverability
4. **Optimize Images**: Use appropriate resolutions for podcast artwork
5. **Enable Caching**: Reduces server load for popular feeds
6. **Monitor Feed Validation**: Ensure feeds validate against standards

Feed Validation
===============

Validate your feeds with these tools:

- `W3C Feed Validator <https://validator.w3.org/feed/>`_ for RSS/Atom
- `Cast Feed Validator <https://castfeedvalidator.com/>`_ for podcasts
- `Apple Podcasts Feed Validator <https://podcastsconnect.apple.com/>`_

Troubleshooting
===============

Common Issues
-------------

1. **Missing Enclosures**: Ensure episodes have ``podcast_audio`` set
2. **Invalid Characters**: Check for special characters in titles/descriptions
3. **Large Feed Size**: Feeds currently include the complete eligible archive;
   there is no supported item-limit setting. Measure response size and generation
   cost before choosing deployment-specific caching or customization.
4. **Cache Issues**: Clear cache after major content updates
