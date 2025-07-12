.. _search_overview:

******
Search
******

Django Cast provides powerful search and filtering capabilities through full-text search and faceted navigation, enabling users to quickly find relevant content.

Full-Text Search
================

Basic Search
------------

Django Cast integrates with Wagtail's search backend to provide full-text search across your content:

- Search through post titles, content, and metadata
- Automatic indexing of new content
- Support for multiple search backends (Elasticsearch, PostgreSQL, etc.)
- Language-aware stemming and ranking

Search Implementation
---------------------

The search functionality is available through:

- Search box in blog templates
- API endpoint for programmatic access
- Faceted navigation interface

Faceted Navigation
==================

Overview
--------

Faceted navigation allows users to filter content by multiple dimensions simultaneously:

- **Date facets**: Browse posts by month or year
- **Category facets**: Filter by content categories
- **Tag facets**: Filter by content tags
- **Search filters**: Combine with full-text search

Configuration
-------------

Configure available facets in your settings:

.. code-block:: python

    # settings.py
    CAST_FILTERSET_FACETS = [
        "search",           # Full-text search box
        "date",             # Date range filtering
        "date_facets",      # Year/month facets
        "category_facets",  # Category filtering
        "tag_facets"        # Tag filtering
    ]

Facet API Endpoints
-------------------

Access facet data programmatically:

- ``/api/facet_counts/`` - List all blogs with facet information
- ``/api/facet_counts/{blog_id}/`` - Detailed facet counts for a specific blog

Example API response:

.. code-block:: json

    {
        "blog_id": 1,
        "facets": {
            "date_facets": {
                "2024": {"count": 15},
                "2023": {"count": 42}
            },
            "category_facets": {
                "tutorials": {"count": 12},
                "news": {"count": 8}
            },
            "tag_facets": {
                "python": {"count": 10},
                "django": {"count": 15}
            }
        }
    }

Search Backends
===============

Wagtail Backend Support
-----------------------

Django Cast supports all Wagtail search backends:

1. **Database Search** (default)

   - No additional setup required
   - Basic full-text search
   - Suitable for small to medium sites

2. **PostgreSQL Search**

   - Advanced full-text search features
   - Better performance than basic database search
   - Requires PostgreSQL database

3. **Elasticsearch**

   - Best performance for large sites
   - Advanced search features
   - Requires Elasticsearch server

Backend Configuration
---------------------

Configure your search backend in settings:

.. code-block:: python

    # PostgreSQL search
    WAGTAILSEARCH_BACKENDS = {
        'default': {
            'BACKEND': 'wagtail.search.backends.postgresql',
        }
    }

    # Elasticsearch
    WAGTAILSEARCH_BACKENDS = {
        'default': {
            'BACKEND': 'wagtail.search.backends.elasticsearch7',
            'URLS': ['http://localhost:9200'],
            'INDEX': 'django_cast',
        }
    }

Search Features
===============

Filter Persistence
------------------

Search filters and facet selections persist across page navigation:

- URL-based state management
- Shareable search URLs
- Browser back/forward support

Search Optimization
-------------------

Performance features for search:

- Cached facet counts
- Indexed search fields
- Optimized query generation
- Minimal database queries

Advanced Search Options
-----------------------

Extend search functionality:

.. code-block:: python

    # Custom search fields
    search_fields = [
        index.SearchField('title', boost=2),
        index.SearchField('body'),
        index.FilterField('date'),
        index.RelatedFields('categories', [
            index.SearchField('name'),
        ]),
    ]

Implementing Search
===================

Template Integration
--------------------

Add search to your templates:

.. code-block:: html

    <!-- Search form -->
    <form method="get" action="{% url 'cast:post_list' %}">
        <input type="text" name="search"
               placeholder="Search posts..."
               value="{{ request.GET.search }}">
        <button type="submit">Search</button>
    </form>

    <!-- Facet filters -->
    {% include "cast/filters/date_facets.html" %}
    {% include "cast/filters/category_facets.html" %}
    {% include "cast/filters/tag_facets.html" %}

View Integration
----------------

Search is automatically handled in post list views:

.. code-block:: python

    # Automatic in BlogDetailView
    # Filters applied via QuerysetData repository
    # Results paginated and cached

Troubleshooting
===============

Common Issues
-------------

1. **No Search Results**

   - Rebuild search index: ``./manage.py update_index``
   - Check search backend configuration
   - Verify content is published

2. **Slow Search Performance**

   - Enable search result caching
   - Optimize indexed fields

3. **Incorrect Facet Counts**

   - Clear cache: ``./manage.py clear_cache``
   - Check facet configuration
   - Verify queryset filters
