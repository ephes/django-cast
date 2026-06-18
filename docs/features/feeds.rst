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

API Access
==========

Feeds are also available via the REST API:

- ``/api/posts/`` - JSON feed of blog posts
- ``/api/episodes/`` - JSON feed of podcast episodes
- Supports filtering, pagination, and field selection
- Machine-readable alternative to XML feeds

Configuration
=============

Feed Limits
-----------

Control the number of items in feeds:

.. code-block:: python

    # In settings.py
    CAST_FEED_ITEM_LIMIT = 50  # Default: 50 items

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

Configure feed cache timeout:

.. code-block:: python

    # Cache feeds for 1 hour
    CAST_FEED_CACHE_TIMEOUT = 3600

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
3. **Large Feed Size**: Reduce ``CAST_FEED_ITEM_LIMIT`` if needed
4. **Cache Issues**: Clear cache after major content updates
