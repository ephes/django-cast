########
Settings
########

Documentation of all the configuration variables you can add to your
``DJANGO_SETTINGS_MODULE`` file.

********
Comments
********

.. _cast_comments_enabled:

CAST_COMMENTS_ENABLED
=====================

Whether or not to enable comments on the site. Defaults to ``False``.

.. _cast_comments_allow_author_edits:

CAST_COMMENTS_ALLOW_AUTHOR_EDITS
================================

Whether to let an anonymous author edit or delete their own comment from the
same browser. Defaults to ``False`` (opt-in). Set to the literal ``True`` to
enable it — a string such as ``"False"`` does not turn it on.

Requires a **server-side session backend**: the ``signed_cookies``
``SESSION_ENGINE`` is rejected by the cast system checks (``cast.E006``),
because comment ownership is tracked in the session and a client-carried list
cannot be revoked. See :ref:`comments_author_edits` for the full behaviour and
privacy notes.

CAST_COMMENTS_OWNED_IDS_CAP
===========================

The maximum number of owned comment ids tracked in a single session. Older
entries are dropped once the cap is reached. Defaults to ``200``; ``0`` means
**no cap** (every id is kept). Only relevant when
:ref:`CAST_COMMENTS_ALLOW_AUTHOR_EDITS <cast_comments_allow_author_edits>` is
enabled.

CAST_COMMENTS_EDIT_RATE_LIMIT
=============================

The maximum number of author edit/delete actions allowed per session within
``CAST_COMMENTS_EDIT_RATE_WINDOW`` seconds. Defaults to ``30``; ``0``
**disables** rate limiting. Only relevant when
:ref:`CAST_COMMENTS_ALLOW_AUTHOR_EDITS <cast_comments_allow_author_edits>` is
enabled.

CAST_COMMENTS_EDIT_RATE_WINDOW
==============================

The length, in seconds, of the rate-limit window used by
``CAST_COMMENTS_EDIT_RATE_LIMIT``. Defaults to ``60`` and must be a positive
integer. Only relevant when
:ref:`CAST_COMMENTS_ALLOW_AUTHOR_EDITS <cast_comments_allow_author_edits>` is
enabled.

**********
Pagination
**********

POST_LIST_PAGINATION
====================

The number of posts to show per page on the user facing blog list page.
Defaults to ``5``.

CHOOSER_PAGINATION
==================

The number of items (audio, video or image) to show per page in the wagtail
admin chooser. Defaults to ``10``.

MENU_ITEM_PAGINATION
====================

The number of items (audio, video, or image) to show per page in the
wagtail admin menu. Defaults to ``20``.

******
Images
******

DELETE_WAGTAIL_IMAGES
=====================

Whether or not to delete the original image when a Wagtail image
model is removed. Defaults to ``True``. This is useful if you are
using an object store like S3 to store your images and want to avoid
having your production images deleted when you try out stuff in your
development environment.

CAST_IMAGE_FORMATS
==================
For which image formats to generate thumbnails / srcset / source renditions. Defaults to
``["jpeg", "avif"]``.

.. _image_slot_dimensions:

CAST_REGULAR_IMAGE_SLOT_DIMENSIONS
===================================

The dimensions of the image slots used for regular (non-gallery) images
in blog posts. Each entry is a ``(width, height)`` tuple. Defaults to
``[(1110, 740)]``.

.. code-block:: python

    CAST_REGULAR_IMAGE_SLOT_DIMENSIONS = [(1110, 740)]

CAST_GALLERY_IMAGE_SLOT_DIMENSIONS
====================================

The dimensions of image slots used for gallery images. The first entry
is the modal (full-size) slot, and the second is the thumbnail slot.
Defaults to ``[(1110, 740), (120, 80)]``.

.. code-block:: python

    CAST_GALLERY_IMAGE_SLOT_DIMENSIONS = [(1110, 740), (120, 80)]

*************
Transcription
*************

CAST_VOXHELM_API_BASE
=====================

Base URL for the Voxhelm service used by ``generate_transcripts``. The value
may point at either the service root (for example
``https://voxhelm.example.com``) or the ``/v1`` API prefix. This can be set as
either a Django setting or an environment variable, or per site through the
Wagtail admin ``Settings -> Voxhelm settings`` screen.

CAST_VOXHELM_API_KEY
====================

Bearer token used for Voxhelm job submission, polling, and artifact download.
This can be set as either a Django setting or an environment variable, or per
site through the Wagtail admin ``Settings -> Voxhelm settings`` screen.

CAST_VOXHELM_MODEL
==================

Optional Voxhelm batch model value for transcript generation. Defaults to
``"auto"``. This can also be managed per site in Wagtail admin.

CAST_VOXHELM_LANGUAGE
=====================

Optional language hint passed through to Voxhelm batch jobs. By default no
language hint is sent. This can also be managed per site in Wagtail admin.

CAST_VOXHELM_DIARIZATION_ENABLED
================================

Whether to request generic speaker diarization for Voxhelm transcript jobs.
Defaults to ``False``. When enabled, django-cast sends
``{"diarization": {"enabled": True}}`` in the top-level Voxhelm job payload;
when disabled or unset, the field is omitted and existing transcription behavior
is unchanged.

This can be set as a Django setting or environment variable. Common boolean
strings such as ``1``, ``true``, ``yes``, and ``on`` enable diarization;
``0``, ``false``, ``no``, and ``off`` disable it. The Wagtail admin
``Settings -> Voxhelm settings`` screen also exposes a site-level value with
three states: inherit the Django/environment configuration, explicitly enabled,
or explicitly disabled. An explicit site-level disabled value overrides a
global enabled value.

The Voxhelm deployment must have its diarization backend configured before this
setting is enabled. Diarization can make full-episode transcription slower, so
production sites should use the queued transcript worker flow rather than
expecting a web request to wait for completion.

Individual audio objects can override this generation default with their
``transcript_diarization_mode`` field. ``inherit`` uses the setting documented
here, ``enabled`` requests diarization even when this setting is false, and
``disabled`` omits both the diarization payload and speaker-count hint for that
audio. The audio-level disabled mode also hides stored speaker labels from
public transcript output without rewriting the stored transcript files.

CAST_VOXHELM_KNOWN_SPEAKER_ENABLED
==================================

Whether to send approved contributor voice references to Voxhelm as
known-speaker reference material for diarized transcript jobs. Defaults to
``False``. When enabled, a diarized job for an episode also sends the approved
voice references of that episode's expected contributors (source ranges into
existing audio, or uploaded clips only when protected storage provides an
absolute temporary URL), never public profile URLs. Hidden contributors are
excluded unless a reference explicitly opts in.

This can be set as a Django setting or environment variable, using the same
boolean strings as ``CAST_VOXHELM_DIARIZATION_ENABLED``. The Wagtail admin
``Settings -> Voxhelm settings`` screen also exposes a site-level value.

Known-speaker recognition requires diarization for the job and applies to
episode-level generation. Voxhelm-returned results are stored as private,
reviewable per-segment suggestions and are not shown publicly until an editor
reviews and approves them.

CAST_VOXHELM_POLL_INTERVAL
==========================

Polling interval in seconds for ``generate_transcripts`` while waiting for a
Voxhelm batch job to finish. Defaults to ``2.0`` seconds.

CAST_VOXHELM_POLL_TIMEOUT
=========================

Maximum time in seconds to wait for a Voxhelm batch job before the command
fails. Defaults to ``900.0`` seconds.

CAST_VOXHELM_REQUEST_TIMEOUT
============================

Per-request HTTP timeout in seconds for Voxhelm API calls and artifact
downloads. Defaults to ``30.0`` seconds. This is separate from
``CAST_VOXHELM_POLL_TIMEOUT``, which controls the overall job wait deadline.

Wagtail Admin Configuration
===========================

django-cast also exposes a site-scoped ``Voxhelm settings`` model in Wagtail
admin for the API base URL, API token, optional model/language preferences,
and optional diarization override. These values take precedence over Django
settings and environment variables for Wagtail-admin-triggered transcript
generation on that site; the diarization field can also be left unset to inherit
the Django/environment value.

Wagtail-admin-triggered transcript completion is queued through Django Tasks.
Production sites that need a database-backed transcript worker should install
the optional ``transcript-worker`` extra. That extra requires a
Wagtail/django-tasks combination compatible with ``django-tasks-db`` 0.12;
Wagtail 7.0 LTS uses ``django-tasks`` 0.7 and is not compatible with that
database backend. Keep the global ``default`` backend immediate, and route
``cast_transcripts`` to the database backend:

.. code-block:: bash

    uv pip install "django-cast[transcript-worker]"

.. code-block:: python

    INSTALLED_APPS += ["django_tasks_db"]

    TASKS = {
        "default": {
            "BACKEND": "django_tasks.backends.immediate.ImmediateBackend",
        },
        "cast_transcripts": {
            "BACKEND": "django_tasks_db.DatabaseBackend",
        },
    }

Run a database worker for that backend, using a stable worker id per deployed
site:

.. code-block:: bash

    python manage.py db_worker --backend cast_transcripts --worker-id homepage-transcripts

*********
Templates
*********

Custom Theme Configuration
==========================

To configure custom themes for the site, use the ``CAST_CUSTOM_THEMES`` setting.
By default, it is set to an empty list ``[]``. Each theme requires two elements:
a name and a display. For instance:

.. code-block:: python

    CAST_CUSTOM_THEMES = [
        # (name, display)
        ("my_theme", "My Theme"),
        ("my_other_theme", "My Other Theme"),
    ]

The display value is the title displayed in the theme selector within the Wagtail
admin panel. The name corresponds to the theme's base directory inside your templates
folder. To create a theme named my_theme, make a directory called ``cast/my_theme``
within your templates folder and place your templates inside.

CAST_FOLLOW_LINKS
=================

Optional mapping of follow links shown in the navbar. Supported keys are
``rss``, ``mastodon``, ``github``, ``bluesky``, ``linkedin``, ``email``,
and ``apple_podcasts``.

When a blog context is available, the ``rss`` value is always set to the
blog-specific XML feed URL, overriding any value from settings. A
``feed_detail`` key is also auto-generated, pointing to the human-readable
feed detail page at ``<slug>/feed/``. The navbar RSS icon links to
``feed_detail`` when available, falling back to ``rss``. The settings
``rss`` value is only used as a fallback on pages without a blog context.

If ``email`` is not provided, it falls back to ``Blog.email`` when available.
Unlike ``rss``, a settings-level ``email`` value takes precedence over
``Blog.email``.

The ``apple_podcasts`` key is used on the feed detail page to show a
subscribe link to Apple Podcasts.

.. code-block:: python

    CAST_FOLLOW_LINKS = {
        # "rss" and "feed_detail" are auto-generated when a blog is present
        "apple_podcasts": "https://podcasts.apple.com/podcast/your-podcast/id123",
        "mastodon": "https://example.social/@account",
        "github": "https://github.com/example",
        "bluesky": "https://bsky.app/profile/example.com",
        "linkedin": "https://www.linkedin.com/in/example/",
        "email": "mailto:hello@example.com",
    }

CAST_PODLOVE_PLAYER_THEMES
==========================

Optional overrides for the Podlove Web Player theme config returned by
``/api/audios/player_config/``. The setting is a mapping keyed by template base
directory name (or ``default``). Each entry can define a shared ``tokens``/``fonts``
override or per-scheme overrides under ``light`` and ``dark``.

.. code-block:: python

    CAST_PODLOVE_PLAYER_THEMES = {
        "bootstrap5": {
            "light": {
                "tokens": {
                    "brand": "#d97706",
                },
            },
            "dark": {
                "tokens": {
                    "brand": "#fbbf24",
                },
            },
        },
        "default": {
            "tokens": {
                "brand": "#ff0000",
            },
        },
    }

CAST_ENABLE_DEV_TOOLS
=====================

Whether to enable dev-only cast views. Defaults to ``False``.

When enabled, these routes are accessible:

- ``/cast/styleguide/``
- ``/cast/components/``
- ``/cast/theme-compare/``
- ``/cast/dev-health/``

When disabled, these routes return ``404``.

CAST_ENABLE_STYLEGUIDE
======================

Deprecated alias for ``CAST_ENABLE_DEV_TOOLS``.

Precedence:

- If only ``CAST_ENABLE_STYLEGUIDE`` is set: use its value and emit ``DeprecationWarning``.
- If only ``CAST_ENABLE_DEV_TOOLS`` is set: use its value.
- If both are set: ``CAST_ENABLE_DEV_TOOLS`` wins and a ``DeprecationWarning`` is emitted.
- If neither is set: default ``False``.

.. note::

   To fully silence the deprecation warning, remove
   ``CAST_ENABLE_STYLEGUIDE`` from settings instead of setting it to ``False``.

CAST_STYLEGUIDE_REMOTE_MEDIA
============================

When enabled, the styleguide can fetch real-world media (images, audio, transcripts)
from configured source URLs. Defaults to ``False``. This is intended for local
development only.

Related settings:

- ``CAST_STYLEGUIDE_IMAGE_SOURCE_URLS``: list of page URLs to scrape for gallery images.
- ``CAST_STYLEGUIDE_VIDEO_SOURCE_URL``: page URL to scrape for a video source.
- ``CAST_STYLEGUIDE_PODCAST_SOURCE_URL``: episode detail URL used to locate audio.
- ``CAST_STYLEGUIDE_TRANSCRIPT_SOURCE_URL``: transcript page URL for transcript segments.
- ``CAST_STYLEGUIDE_IMAGE_LIMIT``: max number of gallery images to import (default ``6``).
- ``CAST_STYLEGUIDE_REMOTE_TIMEOUT``: network timeout in seconds (default ``8``).
- ``CAST_STYLEGUIDE_GENERATE_RENDITIONS``: generate missing renditions while building styleguide galleries
  (default ``False``).
- ``CAST_STYLEGUIDE_TRANSCRIPT_MAX_SEGMENTS``: max transcript segments to keep (default ``12``).
- ``CAST_STYLEGUIDE_TRANSCRIPT_EXCERPT_SEGMENTS``: max transcript segments to show in the
  audio preview (default ``2``).

********
Storages
********

Configure Backup Storage
========================

If you store your media files on S3, you can configure a local backup storage
like this:

.. code-block:: python

    STORAGES = {
      "default": {"BACKEND": "config.settings.local.CustomS3Boto3Storage"},
      "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
      "production": {"BACKEND": "config.settings.local.CustomS3Boto3Storage"},
      "backup": {
          "BACKEND": "django.core.files.storage.FileSystemStorage",
          "OPTIONS": {
              "location": ROOT_DIR.path("backups").path("media"),
          },
      },
      "cast_private_media": {
          "BACKEND": "django.core.files.storage.FileSystemStorage",
          "OPTIONS": {
              "location": ROOT_DIR.path("private").path("media"),
              "base_url": None,
          },
      },
      "cast_public_transcripts": {
          "BACKEND": "config.settings.local.CustomS3Boto3Storage",
      },
    }

``cast_public_transcripts`` stores public transcript artifacts
(``Transcript.podlove``, ``Transcript.vtt``, and ``Transcript.dote``). These
files are publishable output used by public transcript pages, feeds, podcast
clients, and the custom audio player. If the alias is omitted, django-cast uses
``cast_private_media`` when that alias is explicitly configured, preserving
sites that already adapted to the temporary private-storage behavior. If both
aliases are omitted, transcript artifacts use Django's default storage, matching
the original public-media behavior.

``cast_private_media`` stores private django-cast artifacts outside public
media. If omitted, django-cast falls back to ``CAST_PRIVATE_MEDIA_ROOT`` or a
local ``cast-private-media`` directory next to ``MEDIA_ROOT``.

Uploaded contributor voice-reference clips and the private
``Transcript.speakers`` known-speaker sidecar use ``STORAGES["cast_voice_references"]``
when configured. If that dedicated alias is omitted, they fall back to
``cast_private_media`` or the same non-public local private-media fallback.


CAST_AUDIO_UPLOAD_MAX_BYTES
===========================

Maximum accepted size, in bytes, for each uploaded audio file before
django-cast validates the file container or runs ffprobe. Defaults to
``536870912`` (512 MiB).


CAST_VIDEO_UPLOAD_MAX_BYTES
===========================

Maximum accepted size, in bytes, for each uploaded video file before
django-cast validates the file container or runs ffmpeg/ffprobe. Defaults to
``2147483648`` (2 GiB).


CAST_EDITOR_MEDIA_UPLOAD_LOCK_SECONDS
=====================================

Time-to-live, in seconds, for the editor API's per-user audio/video upload
lock. Defaults to ``7200`` (2 hours). The lock is stored in Django's default
cache and is owner-token protected so one request does not release a successor
lock. Multi-worker deployments need a shared cache backend, such as Redis or
Memcached; Django's ``LocMemCache`` only coordinates within one process.


CAST_EDITOR_MEDIA_PROBE_SECONDS
===============================

Cumulative synchronous ffprobe/ffmpeg budget, in seconds, for one editor API
audio or video upload after the file has been received. Defaults to ``10``.
Required audio duration probing failures are returned as ``probe_timeout`` or
``probe_failed``; optional audio chapter extraction and video poster generation
degrade without failing the upload.


******************
Faceted Navigation
******************

CAST_FILTERSET_FACETS
=====================

Controls which ``PostFilterset`` fields are active for blog list filtering.
Default:

.. code-block:: python

    CAST_FILTERSET_FACETS = [
        "search", "date", "date_facets", "category_facets", "tag_facets", "o"
    ]

Supported values:

- ``search``: full-text search
- ``date``: date range filter (``date_after`` / ``date_before``)
- ``date_facets``: month facet (``YYYY-MM``)
- ``category_facets``: category slug facet
- ``tag_facets``: tag slug facet
- ``o``: ordering (``visible_date`` / ``-visible_date``)

Example removing tag facets:

.. code-block:: python

    CAST_FILTERSET_FACETS = [
        "search", "date", "date_facets", "category_facets", "o"
    ]

Modal workflow behavior
~~~~~~~~~~~~~~~~~~~~~~~

``/api/facet_counts/<blog_id>/?mode=modal`` only emits modal groups for
facet names that are both:

- configured in ``CAST_FILTERSET_FACETS``
- one of ``date_facets``, ``tag_facets``, ``category_facets``

Practical recommendations:

- Keep ``search`` enabled so modal counts can track the current query text.
- Keep ``o`` enabled if your UI exposes ordering controls.
- ``date`` (range filter) affects the blog list page, but the
  ``?mode=modal`` facet API does not currently apply date-range
  constraints when computing its counts.


**********
Repository
**********

How to fetch data from the database. By default, the repository fetches
all the data using optimized sql. If you want to fetch data using the
Django ORM, you can set the ``CAST_REPOSITORY`` variable in your settings
to ``"django"``.

.. code-block:: python

    CAST_REPOSITORY = "django"

.. _cdn_configuration:

*********************************
Using a CDN (AWS S3 + Cloudfront)
*********************************

When using a CDN, s3 with cloudfront for example, there are some settings
to put in your production config which are not really obvious:

.. code-block:: python

   AWS_AUTO_CREATE_BUCKET = True
   AWS_S3_REGION_NAME = 'eu-central-1'  # if your region differs from default
   AWS_S3_SIGNATURE_VERSION = 's3v4'
   AWS_S3_FILE_OVERWRITE = True
   AWS_S3_CUSTOM_DOMAIN = env('CLOUDFRONT_DOMAIN')

Took me some time to figure out these settings. Those are additional settings,
assumed you already used the django-cookiecutter template.
