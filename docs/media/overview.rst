Media Handling
==============

Django Cast provides comprehensive media management for images, audio and video. All media is user-owned and integrates seamlessly with Wagtail's admin interface and Django's storage backends.

Overview
--------

Media handling features:

- **User ownership**: All media is associated with the uploading user
- **Multiple formats**: Support for various image, audio, and video formats
- **Automatic processing**: Image renditions, audio duration, video posters
- **Storage flexibility**: Works with local storage, S3, or any Django storage backend
- **Performance optimized**: Rendition caching, metadata storage, bulk operations
- **API access**: Full REST API for media operations

Media Types
-----------

Images
~~~~~~

Django Cast extends Wagtail's image handling with responsive image generation.

**Features**:

- Automatic rendition generation for multiple screen sizes
- Modern format support (AVIF, WebP, JPEG, PNG)
- Responsive images with srcset and sizes attributes
- User-based filtering in admin
- Bulk rendition creation

**Configuration**:

.. code-block:: python

    # Image formats to generate (default)
    CAST_IMAGE_FORMATS = ["jpeg", "avif"]

    # Regular image slots
    CAST_REGULAR_IMAGE_SLOT_DIMENSIONS = [
        (1110, 740),
    ]

    # Gallery image slots
    CAST_GALLERY_IMAGE_SLOT_DIMENSIONS = [
        (1110, 740),  # Modal image
        (120, 80),    # Thumbnail
    ]

Each tuple defines a target slot in the layout. django-cast then generates the
responsive rendition widths needed for multiple pixel densities, so one slot
still produces multiple image files in ``srcset``. Gallery thumbnails normalize
embedded ICC profiles to compact sRGB by default; set
``CAST_GALLERY_THUMBNAIL_RENDITIONS_SRGB = False`` to preserve the previous
thumbnail rendition filter policy.

Audio
~~~~~

Comprehensive audio file management with podcast support.

**Supported Formats**:

- **MP3**: Universal compatibility
- **M4A**: Apple ecosystem
- **OGA**: Ogg Vorbis
- **OPUS**: Modern codec

**Features**:

- Automatic duration detection (requires FFprobe). Decimal seconds are rounded
  to the nearest microsecond, with ties to even. Malformed, negative or nonfinite
  probe values, and values beyond signed 64-bit microsecond storage, fail through
  ``AudioDurationProbeError``. Stored durations are not automatically repaired.
- Multiple format upload support
- Chapter marks with timestamps
- Transcript association
- Podlove Web Player integration
- Metadata caching for performance

**Audio Metadata**:

.. code-block:: python

    # Automatically extracted
    audio.duration  # Duration as timedelta
    audio.data     # JSON metadata including file sizes

Video
~~~~~

Video file support with automatic poster generation in built-in upload workflows.

**Features**:

- Automatic poster frame extraction (requires FFmpeg)
- Configurable poster timestamp
- Dimension detection
- Format support: Any format browsers can play
- MIME type detection

**Poster Generation**:

.. code-block:: python

    from cast.media_derivation import save_video_with_derivations

    # Clear and durably regenerate at a different extraction time.
    video.poster = None
    video.poster_seconds = 5.0
    save_video_with_derivations(video)

Storage Configuration
---------------------

Django Cast supports flexible storage backends.

Local Storage
~~~~~~~~~~~~~

Default configuration using Django's file storage:

.. code-block:: python

    # Media files served from
    MEDIA_URL = '/media/'
    MEDIA_ROOT = BASE_DIR / 'media'

S3 Storage
~~~~~~~~~~

Configure S3 for production:

.. code-block:: python

    # Using django-storages
    DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'

    # Disable Wagtail's automatic cleanup for S3
    DELETE_WAGTAIL_IMAGES = False

Multiple Storage Backends
~~~~~~~~~~~~~~~~~~~~~~~~~

Configure separate storage backends through Django's ``STORAGES`` setting:

.. code-block:: python

    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
        },
        "production": {
            "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
        },
        "backup": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {
                "location": "/backup/media",
            },
        },
        "cast_private_media": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {
                "location": "/srv/django-cast/private-media",
                "base_url": None,
            },
        },
        "cast_public_transcripts": {
            "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
        },
    }

The ``cast_public_transcripts`` storage is used for public Podlove, WebVTT, and DOTe
transcript artifacts. The ``cast_private_media`` storage is reserved for
private django-cast artifacts; known-speaker and glossary-corrections sidecars
and contributor voice references use ``cast_voice_references`` when configured, falling back to
``cast_private_media``.

Image Renditions
----------------

Responsive Image Generation
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Cast automatically generates responsive images:

.. code-block:: html

    <!-- Generated HTML -->
    <picture>
        <source type="image/avif"
                srcset="image.avif.150w 150w,
                        image.avif.300w 300w,
                        image.avif.450w 450w"
                sizes="(max-width: 480px) 100vw, 50vw">
        <img src="image.jpg"
             srcset="image.jpg.150w 150w,
                     image.jpg.300w 300w,
                     image.jpg.450w 450w"
             sizes="(max-width: 480px) 100vw, 50vw"
             alt="Description">
    </picture>

Rendition Filters
~~~~~~~~~~~~~~~~~

Custom rendition generation:

.. code-block:: python

    # Generate specific rendition
    rendition = image.get_rendition('fill-300x300')

    # Bulk create renditions
    gallery.create_renditions()

Performance Optimization
~~~~~~~~~~~~~~~~~~~~~~~~

- Renditions are cached after first generation
- Bulk operations for multiple images
- Repository pattern prefetches renditions
- Minimal database queries

Audio Features
--------------

Chapter Marks
~~~~~~~~~~~~~

Chapter synchronization treats start times as identity and updates the title,
link, and image, including clearing optional URLs. Empty and null URLs are
equivalent when deciding whether a mark needs saving. Replacements validate
unique starts and audio ownership before writing, and serialize the complete
replacement in one transaction. A failed replacement leaves the old set intact.
Unchanged marks retain their identities and are not saved again. Title-only
sources (the audio form, editor API chapter text, and ffprobe extraction) preserve
existing link/image URLs; direct model synchronization can update or clear them.
The admin textarea and ``chapters_as_text`` contain only start times and titles,
so existing URLs never become part of the title during an edit round trip.

Both ``chapters`` and ``chapters_as_text`` sort loaded chapter marks by start.
A prefetched chapter relation needs no further queries; an unprefetched reader
uses one query. JSON link/image and timestamp formatting remain unchanged.

Add navigable chapters to audio:

.. code-block:: python

    from cast.models import ChapterMark

    ChapterMark.objects.create(
        audio=audio,
        start="00:05:30",
        title="Introduction",
        link="https://example.com",
        image="https://example.com/chapter.jpg"
    )

Transcripts
~~~~~~~~~~~

Multiple transcript format support:

.. code-block:: python

    from cast.models import Transcript

    transcript = Transcript.objects.create(
        audio=audio,
        podlove=podlove_file,  # JSON format
        vtt=vtt_file,          # WebVTT format
        dote=dote_file         # DOTe JSON format
    )

Player Integration
~~~~~~~~~~~~~~~~~~

Audio data formatted for Podlove Web Player:

.. code-block:: python

    # Automatic player data generation
    player_data = {
        "audio": audio.audio,        # Format list
        "chapters": audio.chapters,  # Chapter marks
        "title": audio.title,
        "subtitle": audio.subtitle,
    }

Video Processing
----------------

Poster Generation
~~~~~~~~~~~~~~~~~

Automatic poster frame extraction:

.. code-block:: python

    from cast.media_derivation import save_video_with_derivations
    from cast.models import Video

    # Persist the upload and generate its poster.
    video = Video(
        user=request.user,
        title="My Video",
        original=video_file
    )
    save_video_with_derivations(video)

    # Clear and durably regenerate with a different timestamp.
    video.poster = None
    video.poster_seconds = 10.0
    save_video_with_derivations(video)

Dimension Detection
~~~~~~~~~~~~~~~~~~~

Video dimensions and orientation:

.. code-block:: python

    width, height = video._get_video_dimensions()
    is_portrait = height > width

Management Commands
-------------------

Media Maintenance
~~~~~~~~~~~~~~~~~

Find orphaned media files::

    python manage.py media_stale
    python manage.py media_stale --delete  # Remove orphaned managed media files

``media_stale`` only considers files at least 7 days old by default
(``CAST_MEDIA_STALE_MIN_AGE_DAYS``). Unknown storage ages are skipped.
Deletion re-checks age and database references for each file and reports skipped
counts; omit ``--delete`` for the default dry run. See
:doc:`/reference/management-commands` for details.

Backup and Restore
~~~~~~~~~~~~~~~~~~

Sync media between storages::

    # Backup from production to backup storage
    python manage.py media_backup

    # Also refresh backup copies of files that changed in place
    python manage.py media_backup --refresh-changed

    # Restore from backup to production
    python manage.py media_restore

Media Analysis
~~~~~~~~~~~~~~

Analyze storage usage::

    python manage.py media_sizes

Rendition Management
~~~~~~~~~~~~~~~~~~~~

Create missing renditions::

    python manage.py sync_renditions

Regenerate video posters::

    python manage.py recalc_video_posters

User Ownership
--------------

Access Control
~~~~~~~~~~~~~~

All media is filtered by user:

.. code-block:: python

    # In views
    images = Image.objects.filter(user=request.user)

    # In admin
    # Automatically filtered by logged-in user

Search Integration
~~~~~~~~~~~~~~~~~~

Media is searchable:

.. code-block:: python

    from wagtail.search.backends import get_search_backend

    search_backend = get_search_backend()
    results = search_backend.search("podcast", Audio)

API Integration
---------------

Upload via API
~~~~~~~~~~~~~~

.. code-block:: python

    # POST /api/audios/
    {
        "title": "Episode 1",
        "file": <multipart file>
    }

Media in StreamField
~~~~~~~~~~~~~~~~~~~~

Media blocks in post content:

.. code-block:: python

    body = StreamField([
        ("image", ImageChooserBlock()),
        ("gallery", GalleryBlock()),
        ("video", VideoChooserBlock()),
        ("audio", AudioChooserBlock()),
    ])

Best Practices
--------------

Maintenance
~~~~~~~~~~~

1. Run `media_stale` periodically to clean orphaned files
2. Backup media files regularly
3. Test restore procedures

Troubleshooting
---------------

Common Issues
~~~~~~~~~~~~~

**FFmpeg/FFprobe not found**:

Install FFmpeg for audio/video processing::

    # Ubuntu/Debian
    sudo apt-get install ffmpeg

    # macOS
    brew install ffmpeg

**Large file uploads failing**:

Adjust Django settings:

.. code-block:: python

    # Increase upload limits
    DATA_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024  # 50MB
    FILE_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024  # 50MB

**Renditions not generating**:

Check Pillow installation and image format support::

    python -m PIL --version

**S3 permissions errors**:

Ensure bucket policy allows required operations:

- GetObject
- PutObject
- DeleteObject (if DELETE_WAGTAIL_IMAGES is True)

Preview database isolation
~~~~~~~~~~~~~~~~~~~~~~~~~~

Preview hydration reads images, audio, video and rendition inventory from the
post's database, falling back to the read router for an unbound post. It
prefetches renditions from that alias and uses Wagtail's public rendition
creation API for missing ones. This path neither reads nor writes Wagtail's
shared rendition cache, whose keys omit the database alias. Equal image IDs and
hashes in different databases therefore cannot cross-populate that cache. Derived rendition writes use the same alias;
preview still never synchronizes post relationships or creates galleries.

The rendition inventory helper
``get_obsolete_and_missing_rendition_strings(..., using=alias)`` accepts an
optional database alias; existing calls retain their normal router behavior.

Partial media persistence
-------------------------

Audio/video derivation helpers and the ``save()`` compatibility flags honor an
empty ``update_fields`` iterable as a complete no-op, including generators:
no model save, upload validation, probe or storage access occurs.

A partial video save generates a poster only when ``original`` is included in
``update_fields``. A title-only save leaves the stored source and poster alone,
even if the instance holds an unsaved replacement upload. Audio duration and
size reconciliation inspect all formats (including cleared ones), so partial
audio saves derive them only when all four source fields (``mp3``, ``m4a``,
``oga``, ``opus``) are included. Use a full save to derive all metadata, or
explicitly include the source fields; helpers never broaden a partial save to
persist excluded source uploads.

Derivation write database
-------------------------

The derivation services resolve an explicit ``using`` alias first, otherwise
Django's public ``router.db_for_write(..., instance=...)`` chooses the database.
The selected alias owns the transaction, initial model save and derived-field
save. A replica-loaded instance does not override a router that selects primary.

Admin media choosers
--------------------

Audio and Video choosers display the saved media title, hidden ID and Edit link
when reopening the Wagtail editor. Their server, modal and telepath state use
``id``, ``title`` and ``edit_url``. Custom chooser scripts consuming the previous
``edit_link`` key must use ``edit_url`` instead.

If a saved Audio or Video ID no longer exists, the chooser opens empty so an
editor can replace it while editing the rest of the page. Invalid IDs and database
errors still propagate; this recovery does not grant access to media.

Search, collection, tag and pagination controls belong to their own modal, even
when another editor or chooser has matching field IDs. The latest action wins:
new input immediately invalidates previous results, including during the search
debounce. Closing or replacing a modal, or advancing to another chooser step,
retires its event handlers, timers and pending requests. Late responses cannot
publish results or upload errors into another chooser.

Upload fields are resolved within their form, including prefixed field names.
Each upload form admits one pending submission and disables its submit controls.
A failed request enables a deliberate retry; success advances the modal once.
Closing a modal aborts its client request; a server upload already accepted may
still finish, so cancellation does not promise deletion of an uploaded object.

Clearing a chooser resets its hidden value, title, Edit destination and telepath
state together. ``setState(null)`` also restores this empty state. Initial render
and programmatic ``setState`` hydration are silent. A user choice or Clear emits
one bubbling native ``change`` event when the submitted ID changes, allowing
Wagtail's editor to observe media-only edits. Choosing the same ID or clearing
an already empty chooser does not emit another change.

For local regression checks, run ``just js-test``. The opt-in real Wagtail
StreamField journey (choose, clear, duplicate, reorder, save and reopen) is::

    CAST_RUN_BROWSER=1 uv run pytest tests/media_chooser_browser_test.py -v

It requires Playwright Chromium and permission to bind a local test server.
All media and editor records in that journey are synthetic.
