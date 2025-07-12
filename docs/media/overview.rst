Media Handling
==============

Django Cast provides comprehensive media management for images, audio, video, and generic files. All media is user-owned and integrates seamlessly with Wagtail's admin interface and Django's storage backends.

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

    # Regular image dimensions
    CAST_REGULAR_IMAGE_SLOT_DIMENSIONS = {
        "150": "150",    # 150px wide
        "300": "300",
        "450": "450",
        "600": "600",
        "750": "750",
        "900": "900",
        "1050": "1050",
        "1200": "1200",
        "1350": "1350",
        "1500": "1500",
    }

    # Gallery image dimensions
    CAST_GALLERY_IMAGE_SLOT_DIMENSIONS = {
        "150": "150x150",    # 150x150 square crop
        "300": "300x300",
        "600": "600x600",
    }

Audio
~~~~~

Comprehensive audio file management with podcast support.

**Supported Formats**:

- **MP3**: Universal compatibility
- **M4A**: Apple ecosystem
- **OGA**: Ogg Vorbis
- **OPUS**: Modern codec

**Features**:

- Automatic duration detection (requires FFprobe)
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

Video file support with automatic poster generation.

**Features**:

- Automatic poster frame extraction (requires FFmpeg)
- Configurable poster timestamp
- Dimension detection
- Format support: Any format browsers can play
- MIME type detection

**Poster Generation**:

.. code-block:: python

    # Customize poster extraction time
    video.poster_seconds = 5.0  # Extract at 5 seconds
    video.create_poster()       # Regenerate poster

Files
~~~~~

Generic file storage for other document types.

**Features**:

- Simple file upload and storage
- User association
- Path tracking for cleanup

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

Django 4.2+ supports separate storages:

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
    }

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

    # Generate poster at upload
    video = Video.objects.create(
        user=request.user,
        title="My Video",
        original=video_file
    )
    # Poster created automatically

    # Regenerate with different timestamp
    video.poster_seconds = 10.0
    video.create_poster()

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
    python manage.py media_stale --delete  # Remove orphaned files

Backup and Restore
~~~~~~~~~~~~~~~~~~

Sync media between storages::

    # Backup from production to backup storage
    python manage.py media_backup

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
