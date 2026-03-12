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
either a Django setting or an environment variable.

CAST_VOXHELM_API_KEY
====================

Bearer token used for Voxhelm job submission, polling, and artifact download.
This can be set as either a Django setting or an environment variable.

CAST_VOXHELM_MODEL
==================

Optional Voxhelm batch model value for transcript generation. Defaults to
``"auto"``.

CAST_VOXHELM_LANGUAGE
=====================

Optional language hint passed through to Voxhelm batch jobs. By default no
language hint is sent.

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
    }


.. important::

    This will only work if you are using Django >= 4.2.


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
