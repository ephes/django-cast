.. _feeds_overview:

*****
Feeds
*****

Django Cast provides comprehensive feed support for both blogs and podcasts, with RSS and Atom formats, iTunes metadata, and performance optimizations.

Feed Types
==========

Blog Feeds
----------

Blog feeds are available in both RSS and Atom formats, automatically generated from your blog content:

- RSS 2.0 feed with standard blog metadata
- Atom feed with enhanced metadata support
- Feed fields populated from Blog model: title, description, author
- Automatic inclusion of post content (overview and detail sections)

Podcast Feeds
-------------

Podcast feeds extend blog feeds with additional podcast-specific features:

- iTunes podcast metadata (artwork, categories, explicit content marking)
- Audio file enclosures for episode distribution
- Multiple audio format support with separate feeds per format
- Available at: ``feed/podcast/<audio_format>/rss.xml``
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
- **Chapter Marks**: Time-indexed navigation points
- **Transcripts**: Links to VTT and DOTE transcript files

Feed Generation
===============

Repository Pattern
------------------

Feeds use the FeedRepository pattern for optimized generation:

.. code-block:: python

    # Efficient feed generation with minimal queries
    repository = FeedRepository(blog)
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
