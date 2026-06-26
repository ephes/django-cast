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

List videos::

    GET /api/videos/

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

List audio files::

    GET /api/audios/

Retrieve or delete audio::

    GET /api/audios/{id}/
    DELETE /api/audios/{id}/

Podlove player format (public)::

    GET /api/audios/podlove/{id}/
    GET /api/audios/podlove/{id}/post/{post_id}/

Returns audio data formatted for the Podlove Web Player, including chapters,
transcripts, and a top-level ``contributors`` list. Contributors are derived
from non-blank transcript ``speaker``/``voice`` labels in first-appearance
order; the Podlove Web Player resolves transcript segment speakers against
them and renders their names::

    "contributors": [
        {"id": "Speaker 1", "name": "Speaker 1"}
    ]

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

The theme-update endpoint is session-based and does not require
authentication with django-cast's default DRF configuration. It validates the
submitted theme slug and stores the selection using the same theme-selection
flow as the frontend theme switcher.

Comment Moderation
~~~~~~~~~~~~~~~~~~

Export training data for spam filter::

    GET /api/comment_training_data/

Returns comment data for training the Naive Bayes spam classifier.

This endpoint is restricted to staff users. Anonymous and authenticated
non-staff users receive ``403 Forbidden``.

Content Editing (Editor API)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The editor API lives under ``/api/editor/`` and is intended for trusted
clients — scripts, agents, or headless tools — that need to create draft
content without direct database access. It is authentication-mechanism
agnostic: any DRF authentication class that populates ``request.user`` works.
Django-cast ships session authentication by default. Editor endpoints require
an authenticated user with Wagtail admin access and then apply Wagtail page or
collection permissions for the requested object.

**List editable parents**::

    GET /api/editor/parents/

Returns the ``Blog`` and ``Podcast`` pages the authenticated user has
add-child permission for.  Requires authentication; unauthenticated requests are
rejected (``403 Forbidden`` under the default session authentication, ``401`` for
authentication schemes that supply a ``WWW-Authenticate`` challenge).

Example response:

.. code-block:: json

    [
        {"id": 4, "title": "My Blog", "type": "cast.Blog",
         "api_url": "/api/editor/posts/"},
        {"id": 7, "title": "My Podcast", "type": "cast.Podcast",
         "api_url": "/api/editor/posts/"}
    ]

**Create a draft post**::

    POST /api/editor/posts/
    Content-Type: application/json

Creates a draft ``Post`` under the chosen parent page.  The page is saved as a
Wagtail revision and is never published.  Passing ``"publish": true`` is rejected.
(Episode creation mirrors this shape and is a planned follow-up; it is not part of
this slice.)

Referenced media — ``cover_image`` and inline ``image``, ``gallery``,
``audio``, and ``video`` blocks — must be choosable by the caller. Missing and
inaccessible media references are reported the same way (``not_found``) so the
API does not leak objects outside the caller's permissions. ``paragraph`` HTML
is validated through Wagtail's rich-text block, the same path the admin uses on
save.

Request fields:

- ``parent`` (required): ``{"id": <page id>}`` — must be a ``Blog`` or
  ``Podcast`` the caller may add to.
- ``title`` (required): page title.
- ``slug`` (optional): URL slug; auto-derived from ``title`` if omitted.
- ``visible_date`` (optional): ISO 8601 datetime string.
- ``cover_image`` (optional): ``{"id": <image id>, "alt_text": "…"}``.
- ``tags`` (optional): list of tag name strings.
- ``categories`` (optional): list of ``PostCategory`` IDs.
- ``overview`` (required): ordered list of body blocks (see below). Send
  ``[]`` when creating a post that only populates ``detail``.
- ``detail`` (optional): ordered list of body blocks.
- ``publish`` (optional): must be ``false`` or absent.

Body block types accepted in ``overview`` and ``detail``:

.. code-block:: json

    [
        {"type": "heading",   "value": "Notes"},
        {"type": "paragraph", "value": "<p>Rich-text HTML.</p>"},
        {"type": "code",      "value": {"language": "python",
                                        "source": "print('hi')"}},
        {"type": "image",     "value": {"id": 456}},
        {"type": "gallery",   "value": [{"id": 456}, {"id": 789}]},
        {"type": "audio",     "value": {"id": 42}},
        {"type": "video",     "value": {"id": 43}}
    ]

Stored body blocks that this API version cannot safely edit are returned as
``{"type": "unsupported", "value": {"stored_type": "...", "position":
"detail.0"}}`` placeholders. This includes custom or unsupported block types
such as ``embed``, and supported block types whose stored value cannot be
represented as an editable authoring block, such as deleted or inaccessible
media references, empty or malformed galleries, or malformed code blocks. To
preserve one of these blocks while replacing a section, send the placeholder
back with the same ``stored_type`` and ``position``. The placeholder may move to
a different index in the submitted section; ``position`` identifies the original
stored block to preserve. Omitting a placeholder removes that stored block as
part of the full-section replacement.

Full create request example:

.. code-block:: json

    {
      "parent": {"id": 123},
      "title": "Weeknotes 2026-25",
      "slug": "weeknotes-2026-25",
      "visible_date": "2026-06-19T18:00:00+02:00",
      "cover_image": {"id": 456, "alt_text": "Notebook and laptop on a desk"},
      "tags": ["weeknotes"],
      "categories": [],
      "overview": [
        {"type": "heading",   "value": "Notes"},
        {"type": "paragraph", "value": "<p>Shipped the first draft.</p>"},
        {"type": "code",      "value": {"language": "python",
                                        "source": "print(\"hello\")"}},
        {"type": "gallery",   "value": [{"id": 456}, {"id": 789}]}
      ],
      "detail": [
        {"type": "video", "value": {"id": 43}}
      ],
      "publish": false
    }

Success response (``201 Created``):

.. code-block:: json

    {
      "id": 987,
      "type": "cast.Post",
      "title": "Weeknotes 2026-25",
      "slug": "weeknotes-2026-25",
      "parent": {"id": 123},
      "visible_date": "2026-06-19T18:00:00+02:00",
      "tags": ["weeknotes"],
      "categories": [],
      "cover_image": {"id": 456, "alt_text": "Notebook and laptop on a desk"},
      "overview": [
        {"type": "heading",   "value": "Notes"},
        {"type": "paragraph", "value": "<p>Shipped the first draft.</p>"},
        {"type": "code",      "value": {"language": "python",
                                        "source": "print(\"hello\")"}},
        {"type": "gallery",   "value": [{"id": 456}, {"id": 789}]}
      ],
      "detail": [
        {"type": "video", "value": {"id": 43}}
      ],
      "latest_revision_id": 6543,
      "live": false,
      "status": "draft",
      "preview_url": "/admin/pages/987/view_draft/",
      "edit_url": "/admin/pages/987/edit/",
      "api_url": "/api/editor/posts/987/"
    }

**Read a draft post**::

    GET /api/editor/posts/{id}/

Returns editable metadata, normalized ``overview`` and ``detail`` block lists
(same structure as the create request), revision metadata, and admin URLs for
an existing draft. Missing sections are returned as empty lists. Requires the
caller to have edit permission for the page.
Use this endpoint — not the public Wagtail pages API — to read back a draft:
the Wagtail pages API returns only live pages and does not expose authoring
source or revision IDs.

**Update a draft post**::

    PATCH /api/editor/posts/{id}/
    Content-Type: application/json

Creates a new Wagtail draft revision for an existing ``Post``.  The request
must include the ``latest_revision_id`` returned by ``GET`` or the previous
write response as ``base_revision_id``.  Omitted fields are left unchanged; a
provided ``overview`` or ``detail`` replaces that whole section, including when
the supplied value is an empty list. Omitted sections and unsupported/custom
top-level body sections are preserved. At least one mutable field besides
``base_revision_id`` is required; ``publish: false`` does not count as a
mutable field and ``publish: true`` is rejected as unsupported.

Update fields:

- ``base_revision_id`` (required): optimistic concurrency token.
- ``title`` (optional): page title.
- ``slug`` (optional): URL slug; must remain unique under the same parent.
- ``visible_date`` (optional): ISO 8601 datetime string.
- ``cover_image`` (optional): ``{"id": <image id>, "alt_text": "…"}``, or
  ``null`` to clear the draft cover image.
- ``tags`` (optional): full replacement list of tag name strings.
- ``categories`` (optional): full replacement list of ``PostCategory`` IDs.
- ``overview`` (optional): full replacement ordered list of body blocks.
- ``detail`` (optional): full replacement ordered list of body blocks.
- ``publish`` (optional): must be ``false`` or absent.

Example update request:

.. code-block:: json

    {
      "base_revision_id": 6543,
      "title": "Updated draft title",
      "overview": [
        {"type": "paragraph", "value": "<p>Updated draft text.</p>"}
      ]
    }

A stale base revision returns ``409 Conflict``:

.. code-block:: json

    {
      "code": "revision_conflict",
      "detail": "The page has a newer revision than the submitted base revision.",
      "current_revision_id": 6550,
      "submitted_base_revision_id": 6543,
      "edit_url": "/admin/pages/987/edit/"
    }

**Error envelopes**

Validation errors (``400 Bad Request``):

.. code-block:: json

    {
      "code": "validation_error",
      "errors": {
        "title": [{"code": "required", "message": "This field is required."}],
        "overview.3.value.1.id": [
          {"code": "not_found", "message": "Image 789 does not exist."}
        ]
      }
    }

Field paths in ``errors`` follow dot notation into the request body so that
clients can locate and repair individual fields without guessing.

Permission errors (``403 Forbidden``):

.. code-block:: json

    {"code": "permission_denied", "detail": "…"}

Permission denials tied to a parent page, such as create-under-page checks, may
also include ``parent_id``:

.. code-block:: json

    {"code": "permission_denied", "detail": "…", "parent_id": 123}

Missing posts (``404 Not Found``):

.. code-block:: json

    {"code": "not_found", "detail": "Post not found."}

Whole-request editor media failures use flat error bodies. Current media
upload codes include ``no_upload_collection`` (403), ``post_save_permission_denied``
(403), ``probe_timeout`` (422), ``probe_failed`` (422), ``rate_limited`` (429), and
``cleanup_failed`` (500). Form and field problems use the validation envelope;
``non_field_errors`` is the reserved key for request-wide validation errors.

**Editor media endpoints**

Editor media endpoints use the shared pagination envelope and accept only their
documented query parameters. Unsupported parameters, such as ``tags=`` instead
of repeatable ``tag=``, return ``validation_error`` with
``unsupported_parameter``.

List selectable media::

    GET /api/editor/media/images/?q=desk&tag=weeknotes
    GET /api/editor/media/audios/?q=episode&tag=weeknotes
    GET /api/editor/media/videos/?q=demo&tag=weeknotes

The list endpoints return only objects the caller may choose. ``q`` is a
deterministic database filter: image and video titles are searched with
``icontains``; audio title and subtitle are searched with ``icontains``.
Repeatable ``tag`` filters match exact stored tag names and are ANDed. Results
are ordered newest first (images by ``created_at``, audio/video by ``created``),
then by descending ID. Media file fields use relative URLs; pagination links
may be absolute. Relative media URLs assume the application serves or proxies
media from the same origin; deployments whose storage requires absolute signed
CDN URLs should provide a same-origin media path for editor API consumers.

Image result shape:

.. code-block:: json

    {
      "id": 456,
      "type": "wagtailimages.Image",
      "title": "Desk photo",
      "file": "/media/original_images/desk.jpg",
      "width": 1600,
      "height": 900,
      "collection": {"id": 1, "name": "Root"},
      "tags": ["weeknotes"],
      "edit_url": "/admin/images/456/"
    }

Audio result shape:

.. code-block:: json

    {
      "id": 42,
      "type": "cast.Audio",
      "title": "Episode audio",
      "subtitle": "Interview mix",
      "transcript_diarization_mode": "inherit",
      "file_formats": "m4a mp3",
      "mp3": "/media/cast_audio/episode.mp3",
      "m4a": "/media/cast_audio/episode.m4a",
      "oga": null,
      "opus": null,
      "collection": {"id": 1, "name": "Root"},
      "tags": ["weeknotes"],
      "edit_url": "/admin/castaudio/edit/42/"
    }

Video result shape:

.. code-block:: json

    {
      "id": 43,
      "type": "cast.Video",
      "title": "Demo clip",
      "original": "/media/cast_videos/demo.mp4",
      "poster": "/media/cast_videos/poster/demo.jpg",
      "collection": {"id": 1, "name": "Root"},
      "tags": ["weeknotes"],
      "edit_url": "/admin/castvideo/edit/43/"
    }

Upload media::

    POST /api/editor/media/images/
    POST /api/editor/media/audios/
    POST /api/editor/media/videos/
    Content-Type: multipart/form-data

Image uploads accept ``title``, ``file``, ``tags``, and optional ``collection``.
Audio uploads accept ``title``, ``subtitle``, ``transcript_diarization_mode``,
one of ``m4a``/``mp3``/``oga``/``opus``, ``tags``, ``chaptermarks``, and
optional ``collection``. ``transcript_diarization_mode=enabled`` is rejected in
this slice; use ``inherit`` or ``disabled``. Video uploads accept ``title``,
``original``, optional ``poster``, ``tags``, and optional ``collection``.

If ``collection`` is omitted and exactly one usable upload collection exists,
that collection is selected. If none exists, upload returns
``no_upload_collection``. If more than one exists, upload returns a validation
error on ``collection`` with code ``ambiguous``. A supplied missing or unusable
collection returns ``collection_permission_denied`` on ``collection``; malformed
collection values return ``invalid``.

Audio and video uploads share a one-in-flight lock per authenticated user; a
second concurrent audio/video upload returns ``rate_limited``. The lock uses
the default Django cache and requires a shared cache backend, such as Redis or
Memcached, to be process-wide in multi-worker deployments; Django's
``LocMemCache`` only protects a single process. Configure
``CAST_EDITOR_MEDIA_UPLOAD_LOCK_SECONDS`` when deployments need a longer or
shorter owner-token TTL. Editor audio duration probing and optional chapter
extraction run inside a cumulative request-path budget controlled by
``CAST_EDITOR_MEDIA_PROBE_SECONDS``. Required audio probing timeout returns
``probe_timeout`` and the failed object/files are cleaned up. Required audio
probing failures such as invalid ffprobe output or an unavailable ffprobe
binary return ``probe_failed`` and are also cleaned up. Optional chapter
extraction failures are logged and save the audio without extracted chapter
marks; malformed individual chapter entries are skipped while valid entries are
kept. Video poster generation is optional display enrichment; timeout or
ffmpeg/ffprobe failure during poster generation does not fail the upload, and
upload can succeed with ``poster: null``.

Discover upload collections::

    GET /api/editor/media/collections/?type=image
    GET /api/editor/media/collections/?type=audio
    GET /api/editor/media/collections/?type=video

The ``type`` parameter is required and must be one of ``image``, ``audio``, or
``video``. Responses use the same pagination envelope. Items include ``id``,
``name``, display-only ``breadcrumb``, and ``ancestors`` from root to parent.
Discovery returns candidate upload targets; custom permission policies can
still make a saved audio/video object fail the defensive post-save choose check.

**Draft-only and Wagtail permissions**

The editor API never publishes.  Create requests save Wagtail draft revisions,
so newly-created pages are returned with ``live: false`` and do not appear in
the public Wagtail pages API.  Updating an already-live page creates an
unpublished draft revision and returns ``status: "draft"`` while ``live`` stays
``true``.  Publishing is a separate follow-up action not yet implemented.

Authorization uses standard Wagtail page permissions:

- ``GET /api/editor/parents/`` — lists pages where the caller has
  add-child permission.
- ``POST /api/editor/posts/`` — requires add-child permission on the
  selected parent.
- ``GET /api/editor/posts/{id}/`` — requires edit permission for the page.
- ``PATCH /api/editor/posts/{id}/`` — requires edit permission for the page.

Pagination
----------

List endpoints support pagination:

- Default page size: 40
- Maximum page size: 200
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

The file upload endpoint accepts ``multipart/form-data``:

.. code-block:: javascript

    const formData = new FormData();
    formData.append('original', fileInput.files[0]);

    fetch('/api/upload_video/', {
        method: 'POST',
        body: formData,
        credentials: 'include'  // Include session cookie
    });

Unsupported media extensions, content types, container signatures, or files
over the configured upload size limit are rejected with ``400 Bad Request`` and
field-level JSON errors. Audio uploads are handled by the Wagtail admin and
chooser views rather than a public DRF upload endpoint.

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
- Media uploads are validated for type and size before metadata extraction
- Images API includes null byte protection
