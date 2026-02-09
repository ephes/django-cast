API Documentation
=================

Django Cast provides a comprehensive REST API for content management, media handling, and theme customization. The API supports both traditional Django session authentication and enables headless CMS usage.

Overview
--------

The API is available at ``/api/`` and includes:

- Media management (audio, video, images)
- Content access via Wagtail API
- Faceted search capabilities
- Theme management
- Comment moderation data export

Authentication
--------------

Authenticated endpoints use Django session authentication (for example ``/api/videos/``,
``/api/audios/``, and ``/api/comment_training_data/``).

Browsable-API login/logout routes are project-specific. In the example project they are:

- ``/api-auth/login/``
- ``/api-auth/logout/``

Public endpoints (no authentication required) include:

- Podlove audio format
- Player configuration
- Theme listing and theme update
- Wagtail pages and images
- Facet counts

Endpoints
---------

Media Management
~~~~~~~~~~~~~~~~

**Videos**

List and create videos::

    GET /api/videos/
    POST /api/videos/

Retrieve or delete a video::

    GET /api/videos/{id}/
    DELETE /api/videos/{id}/

Upload video file::

    POST /api/upload_video/

Example response::

    {
        "id": 1,
        "url": "http://localhost:8000/api/videos/1/",
        "original": "http://localhost:8000/media/cast_videos/demo.mp4",
        "poster": "http://localhost:8000/media/cast_videos/poster/poster_abcd.jpg",
        "poster_thumbnail": "http://localhost:8000/media/images/poster.width-300.jpg"
    }

**Audio**

List and create audio files::

    GET /api/audios/
    POST /api/audios/

Retrieve or delete audio::

    GET /api/audios/{id}/
    DELETE /api/audios/{id}/

Podlove player format (public)::

    GET /api/audios/podlove/{id}/
    GET /api/audios/podlove/{id}/post/{post_id}/

Returns audio data formatted for the Podlove Web Player, including chapters and transcripts.

Audio list/detail responses include these serializer fields:

.. code-block:: json

    {
        "id": 12,
        "name": "Episode 12",
        "file_formats": "m4a mp3",
        "url": "http://localhost:8000/api/audios/12/",
        "podlove": "http://localhost:8000/api/audios/podlove/12/",
        "mp3": "http://localhost:8000/media/cast_audio/episode-12.mp3"
    }

Player configuration::

    GET /api/audios/player_config/
    GET /api/audios/player_config/?color_scheme=dark

Returns player theme and configuration settings. The ``color_scheme`` query
parameter accepts ``light`` or ``dark`` and can be used by themes with
client-side color mode switching.

Content Access
~~~~~~~~~~~~~~

**Wagtail Pages API**

Access page content with filtering::

    GET /api/wagtail/pages/
    GET /api/wagtail/pages/{id}/

Standard Wagtail filters:

- ``type``: Filter by page type (e.g., ``cast.Post``, ``cast.Episode``)
- ``child_of``: Filter to only include direct children of the page with this ID
- ``descendant_of``: Filter to include all descendants of the page with this ID
- ``translation_of``: Filter to only include translations of the page with this ID
- ``fields``: Comma-separated list of fields to include in response
- ``order``: Ordering field (prefix with ``-`` for descending)
- ``slug``: Filter by slug (exact match)
- ``show_in_menus``: Filter pages shown in menus
- ``search``: Full-text search (note: when using ``use_post_filter=true``, this uses Django Cast's enhanced search)
- ``limit``: Number of results per page
- ``offset``: Number of results to skip

Django Cast custom filters (requires ``use_post_filter=true``):

- ``use_post_filter``: Set to ``true`` to enable Django Cast's enhanced filtering
- ``date_facets``: Filter by year-month (format: ``YYYY-MM``)
- ``category_facets``: Filter by category slug
- ``tag_facets``: Filter by tag slug
- ``date_after``: Filter posts after date (format: ``YYYY-MM-DD``)
- ``date_before``: Filter posts before date (format: ``YYYY-MM-DD``)
- ``o``: Ordering by visible_date (use ``-visible_date`` for descending)

Example requests:

Standard Wagtail filtering::

    GET /api/wagtail/pages/?type=cast.Post&child_of=4

Enhanced Django Cast filtering::

    GET /api/wagtail/pages/?type=cast.Post&use_post_filter=true&category_facets=tech&date_after=2024-01-01

Filter posts by month::

    GET /api/wagtail/pages/?type=cast.Post&use_post_filter=true&date_facets=2024-03

Combined filters::

    GET /api/wagtail/pages/?type=cast.Post&child_of=4&use_post_filter=true&tag_facets=python&date_facets=2024-03

**Images API**

Access images::

    GET /api/wagtail/images/
    GET /api/wagtail/images/{id}/

Search and Discovery
~~~~~~~~~~~~~~~~~~~~

**Facet Counts**

List blogs that expose the detail endpoint::

    GET /api/facet_counts/

If cast is mounted at ``/cast/``, this becomes ``/cast/api/facet_counts/``.

Example list response::

    {
        "count": 1,
        "next": null,
        "previous": null,
        "results": [
            {
                "id": 4,
                "url": "http://localhost:8000/cast/api/facet_counts/4/"
            }
        ]
    }

Detail endpoint supports two response modes:

Legacy mode (default)
^^^^^^^^^^^^^^^^^^^^^

Request::

    GET /api/facet_counts/{blog_id}/

Optional filter params are passed through the same filterset as the blog list:
``search``, ``date_after``, ``date_before``, ``date_facets``, ``category_facets``, ``tag_facets``, ``o``.

Example::

    GET /api/facet_counts/4/?search=python&tag_facets=django

Legacy response shape::

    {
        "id": 4,
        "url": "http://localhost:8000/cast/api/facet_counts/4/",
        "facet_counts": {
            "date_facets": [
                {"slug": "2026-02", "name": "2026-02", "count": 2}
            ],
            "category_facets": [
                {"slug": "til", "name": "Today I Learned", "count": 1}
            ],
            "tag_facets": [
                {"slug": "django", "name": "django", "count": 1}
            ]
        }
    }

Modal mode
^^^^^^^^^^

Request::

    GET /api/facet_counts/{blog_id}/?mode=modal

Supported modal selection params:
``search``, ``date_facets``, ``category_facets``, ``tag_facets``, ``o``.

Example::

    GET /api/facet_counts/4/?mode=modal&search=python&tag_facets=django&category_facets=til

Modal response shape::

    {
        "mode": "modal",
        "result_count": 1,
        "groups": {
            "date_facets": {
                "selected": "",
                "all_count": 1,
                "options": [
                    {"slug": "2026-02", "name": "2026-02", "count": 1},
                    {"slug": "2026-01", "name": "2026-01", "count": 0}
                ]
            },
            "tag_facets": {
                "selected": "django",
                "all_count": 2,
                "options": [
                    {"slug": "django", "name": "django", "count": 1},
                    {"slug": "python", "name": "python", "count": 1}
                ]
            },
            "category_facets": {
                "selected": "til",
                "all_count": 2,
                "options": [
                    {"slug": "til", "name": "Today I Learned", "count": 1},
                    {"slug": "weeknotes", "name": "WeekNotes", "count": 1}
                ]
            }
        }
    }

Notes:

- Only ``mode=modal`` enables modal responses; unknown modes fall back to legacy output.
- Group keys are limited to configured facet groups from ``CAST_FILTERSET_FACETS`` intersected with:
  ``date_facets``, ``tag_facets``, ``category_facets``.
- Legacy mode uses conjunctive counts (fully filtered result set).
- Modal mode uses disjunctive per-group counts (temporarily excludes the group being counted).
- ``options`` include zero-count values so modal UIs can keep disabled choices visible.
- ``o`` is accepted for URL-state parity but does not change modal counts.
- ``date_after``/``date_before`` are part of the list filterset, but are not currently applied in modal mode.

Theme Management
~~~~~~~~~~~~~~~~

List available themes::

    GET /api/themes/

Update selected theme::

    POST /api/update_theme/
    Content-Type: application/json

    {"theme_slug": "bootstrap5"}

Comment Moderation
~~~~~~~~~~~~~~~~~~

Export training data for spam filter::

    GET /api/comment_training_data/

Returns comment data for training the Naive Bayes spam classifier.

Pagination
----------

List endpoints support pagination:

- Default page size: 40
- Maximum page size: 10000
- Query parameters: ``page``, ``pageSize``

Example::

    GET /api/videos/?page=2&pageSize=20

Response format::

    {
        "count": 100,
        "next": "http://example.com/api/videos/?page=3",
        "previous": "http://example.com/api/videos/?page=1",
        "results": [...]
    }

File Uploads
------------

File upload endpoints accept ``multipart/form-data``:

.. code-block:: javascript

    const formData = new FormData();
    formData.append('original', fileInput.files[0]);

    fetch('/api/upload_video/', {
        method: 'POST',
        body: formData,
        credentials: 'include'  // Include session cookie
    });

For ``POST /api/audios/``, send audio format fields such as ``m4a``, ``mp3``,
``oga``, or ``opus`` (plus optional metadata like ``title``/``subtitle``).

Error Handling
--------------

The API returns standard HTTP status codes:

- ``200 OK``: Success
- ``201 Created``: Resource created
- ``400 Bad Request``: Invalid request data
- ``401 Unauthorized``: Authentication required
- ``403 Forbidden``: Permission denied
- ``404 Not Found``: Resource not found
- ``500 Internal Server Error``: Server error

Error responses include a detail message::

    {
        "detail": "Authentication credentials were not provided."
    }

Using the API
-------------

JavaScript Example
~~~~~~~~~~~~~~~~~~

Fetching posts with facets:

.. code-block:: javascript

    async function fetchPosts(categorySlug, page = 1) {
        const response = await fetch(
            `/api/wagtail/pages/?type=cast.Post&child_of=4&use_post_filter=true&category_facets=${categorySlug}&page=${page}`,
            { credentials: 'include' }
        );
        return await response.json();
    }

Python Client Example
~~~~~~~~~~~~~~~~~~~~~

Using the API from Python with httpx:

.. code-block:: python

    import httpx

    # Create client for session persistence
    with httpx.Client() as client:
        # Request modal facet counts for a specific blog
        response = client.get(
            "https://example.com/api/facet_counts/4/",
            params={
                "mode": "modal",
                "search": "python",
                "tag_facets": "django",
            },
        )
        facet_data = response.json()

Headless CMS Usage
------------------

Django Cast can function as a headless CMS by:

1. Using the Wagtail Pages API to fetch content
2. Implementing a frontend application (React, Vue, etc.)
3. Optionally using theme packages like ``cast-vue``

Example Vue.js integration:

.. code-block:: javascript

    // Fetch blog posts
    const posts = await fetch('/api/wagtail/pages/?type=cast.Post')
        .then(r => r.json());

    // Get facet counts for filtering
    const facets = await fetch('/api/facet_counts/1/')
        .then(r => r.json());

Performance Considerations
--------------------------

- Use field limiting to reduce payload size: ``?fields=title,slug,date``
- Implement client-side caching for static content
- Use pagination for large result sets
- Facet counts are optimized at the repository level

Security Notes
--------------

- All media endpoints filter by authenticated user
- CSRF protection is enabled for state-changing operations
- File uploads are validated for type and size
- Images API includes null byte protection
