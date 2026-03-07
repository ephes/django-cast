.. _performance_overview:

***********
Performance
***********

Django Cast is built with performance as a core consideration, using advanced patterns and caching strategies to deliver content efficiently even under high load.

Architecture Overview
=====================

Repository Pattern
------------------

Django Cast uses a sophisticated repository pattern that sits between the database and Django's ORM:

.. code-block:: text

    Database → Django ORM/Raw SQL → Repository → Dict → JSON Cache → Dict → Django Models → Template

This architecture enables:

- Caching between database queries and model instantiation
- Minimal database queries through aggressive prefetching
- JSON-serialized cache storage for complex querysets

Key Components
--------------

1. **PostQuerySnapshot Base Class**: Foundation for all repositories
2. **PostDetailContext**: Optimized single post queries
3. **BlogIndexContext**: Efficient post list queries with filtering/pagination
4. **FeedContext**: Specialized for RSS/Atom generation
5. **RenditionsForPost lookups**: Image rendition management

Query Optimization
==================

Prefetch Strategies
-------------------

Repositories use aggressive prefetching to minimize queries:

.. code-block:: python

    # Bad: N+1 queries
    for post in posts:
        print(post.author.name)  # Query per post
        print(post.images.all())  # Query per post

    # Good: prefetch once and reuse lookups
    snapshot = PostQuerySnapshot.create_from_post_queryset(
        request=request,
        site=site,
        queryset=posts,
    )
    # Snapshot contains prefetched media and renditions by post ID

Optimization Techniques
-----------------------

- **select_related**: For one-to-many relationships
- **prefetch_related**: For many-to-many relationships
- **only()**: Load only required fields
- **defer()**: Exclude expensive fields
- **Prefetch objects**: Custom prefetch queries

Example implementation:

.. code-block:: python

    snapshot = PostQuerySnapshot.create_from_post_queryset(
        request=request,
        site=site,
        queryset=blog.get_published_posts().select_related("owner", "cover_image"),
    )

Caching Strategies
==================

Multi-Level Caching
-------------------

Django Cast implements caching at multiple levels:

1. **Repository Cache**

   - JSON-serialized query results
   - Filesystem-based storage
   - Automatic invalidation
   - Configurable timeout

2. **Rendition Cache**

   - Generated image sizes
   - AVIF and JPEG formats
   - Lazy generation
   - Persistent storage

3. **Feed Cache**

   - Complete RSS/Atom feeds
   - Reduces XML generation
   - Conditional GET support
   - Hourly refresh default

Cache Configuration
-------------------

.. code-block:: python

    # Repository cache settings
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache',
            'LOCATION': '/var/tmp/django_cache',
            'TIMEOUT': 3600,  # 1 hour
        }
    }

    # Feed cache timeout
    CAST_FEED_CACHE_TIMEOUT = 3600  # 1 hour

    # Image slot settings
    CAST_REGULAR_IMAGE_SLOT_DIMENSIONS = [
        (1110, 740),
    ]
    CAST_GALLERY_IMAGE_SLOT_DIMENSIONS = [
        (1110, 740),
        (120, 80),
    ]

These settings define layout slots. django-cast derives multiple rendition
widths per slot for responsive ``srcset`` output.

Media Optimization
==================

Image Handling
--------------

Responsive images with automatic optimization:

- **Format Selection**: AVIF with JPEG fallback
- **Size Variants**: Multiple renditions per breakpoint
- **Lazy Loading**: Native browser lazy loading
- **Bulk Generation**: Renditions created in batches

Example rendition generation:

.. code-block:: python

    # Automatic rendition creation
    for width in [150, 300, 600, 900, 1200]:
        image.get_rendition(f'width-{width}')
        image.get_rendition(f'width-{width}|format-avif')

Audio File Optimization
-----------------------

- Multiple format support (MP3, M4A, OGG, OPUS)
- File size caching with admin action
- Metadata extraction optimization
- Progressive download support

Bulk Operations
===============

Admin Actions
-------------

Performance-focused admin actions:

1. **Cache File Sizes**: Update all audio file sizes
2. **Generate Renditions**: Bulk create image renditions
3. **Clear Caches**: Selective cache invalidation
4. **Rebuild Indexes**: Search index optimization

Example admin action:

.. code-block:: python

    @admin.action(description="Cache file sizes")
    def cache_file_sizes(modeladmin, request, queryset):
        for audio in queryset:
            audio.cache_audio_file_sizes()

Database Optimization
=====================

Index Strategy
--------------

Key database indexes for performance:

.. code-block:: python

    class Meta:
        indexes = [
            models.Index(fields=['date', 'blog']),
            models.Index(fields=['is_published', 'date']),
            models.Index(fields=['author', 'is_published']),
        ]

Query Reduction
---------------

Techniques to minimize database load:

- Denormalized fields for common queries
- Computed fields stored in database
- Aggregate queries cached
- Raw SQL for complex operations

Monitoring Performance
======================

Debug Toolbar
-------------

Use Django Debug Toolbar to identify issues:

.. code-block:: python

    # Development settings
    if DEBUG:
        INSTALLED_APPS += ['debug_toolbar']
        MIDDLEWARE += ['debug_toolbar.middleware.DebugToolbarMiddleware']

Performance Metrics
-------------------

Track key metrics:

1. **Query Count**: Aim for < 10 queries per page
2. **Query Time**: Target < 100ms total
3. **Cache Hit Rate**: Should be > 80%
4. **Page Load Time**: Target < 1 second

Spam Filter Performance
=======================

The integrated spam filter is optimized for speed:

- Pure Python implementation (100 lines)
- Naive Bayes algorithm
- In-memory classification
- Performance metrics in admin:
  - Precision/Recall/F1 scores
  - Training time tracking
  - Real-time classification

Best Practices
==============

1. **Use Repositories**: Always access data through repositories
2. **Cache Aggressively**: Cache expensive operations
3. **Prefetch Related Data**: Avoid N+1 queries
4. **Monitor Query Count**: Use debug toolbar in development
5. **Optimize Images**: Let the system handle renditions
6. **Bulk Operations**: Process multiple items together
7. **Index Strategically**: Add indexes for common queries

Common Performance Issues
=========================

1. **High Query Count**

   - Use repository pattern
   - Add prefetch_related calls
   - Check for missing select_related

2. **Slow Image Loading**

   - Enable rendition caching
   - Use lazy loading
   - Check rendition dimensions

3. **Feed Generation Timeout**

   - Enable feed caching
   - Reduce feed item limit
   - Use FeedContext

4. **Search Performance**

   - Rebuild search indexes
   - Check database indexes
