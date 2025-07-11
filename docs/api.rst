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

Query parameters:

- ``type``: Filter by page type (e.g., ``cast.Post``)
- ``fields``: Comma-separated list of fields to include
- ``order``: Ordering field (prefix with ``-`` for descending)
- ``search``: Full-text search
- ``slug``: Filter by slug
- ``show_in_menus``: Filter pages shown in menus

Custom filters for posts:

- ``date_facets``: Include date facets in response
- ``category_facets``: Include category facets
- ``date_from``: Filter posts from date (YYYY-MM-DD)
- ``date_to``: Filter posts until date
- ``category``: Filter by category slug
- ``tag``: Filter by tag name

Example filtered request::

    GET /api/wagtail/pages/?type=cast.Post&category=tech&date_from=2024-01-01

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
