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

Most API endpoints require authentication:

- **Method**: Django session authentication
- **Login**: ``/api/auth/login/``
- **Logout**: ``/api/auth/logout/``

Public endpoints (no authentication required):

- Podlove audio format
- Player configuration
- Theme listing
- Wagtail pages and images

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
        "title": "My Video",
        "file": "/media/videos/my-video.mp4",
        "poster": "/media/video-posters/my-video.jpg",
        "created": "2024-01-01T10:00:00Z"
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

Returns audio data formatted for the Podlove Web Player, including chapters and transcripts.

Player configuration::

    GET /api/audios/player_config/

Returns player theme and configuration settings.

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

List blogs with facet information::

    GET /api/facet_counts/

Get detailed facets for a blog::

    GET /api/facet_counts/{blog_id}/

Response includes:

- Category counts
- Tag counts
- Date facets (posts per month/year)
- Total post count

Example response::

    {
        "id": 1,
        "title": "My Blog",
        "post_count": 42,
        "facet_counts": {
            "categories": [
                {"slug": "tech", "name": "Technology", "count": 15},
                {"slug": "news", "name": "News", "count": 10}
            ],
            "tags": [
                {"name": "python", "count": 8},
                {"name": "django", "count": 12}
            ],
            "dates": {
                "2024": {"count": 20, "months": {"01": 5, "02": 3}},
                "2023": {"count": 22}
            }
        }
    }

Theme Management
~~~~~~~~~~~~~~~~

List available themes::

    GET /api/themes/

Update selected theme::

    POST /api/update_theme/
    Content-Type: application/json

    {"theme": "bootstrap5"}

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
- Query parameters: ``page``, ``page_size``

Example::

    GET /api/videos/?page=2&page_size=20

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
    formData.append('file', fileInput.files[0]);
    formData.append('title', 'My Video');

    fetch('/api/upload_video/', {
        method: 'POST',
        body: formData,
        credentials: 'include'  // Include session cookie
    });

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

    async function fetchPosts(category, page = 1) {
        const response = await fetch(
            `/api/wagtail/pages/?type=cast.Post&category=${category}&page=${page}`,
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
        # Login
        client.post('https://example.com/api/auth/login/', data={
            'username': 'user',
            'password': 'pass'
        })

        # Upload audio file
        with open('podcast.mp3', 'rb') as f:
            response = client.post(
                'https://example.com/api/audios/',
                files={'file': f},
                data={'title': 'Episode 1'}
            )

        audio_data = response.json()

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
