.. _cast_management_commands:

*********************
Django-Admin Commands
*********************

Django Cast provides several management commands, primarily for managing
media files, image renditions, and reference content.

Image Renditions
================

sync_renditions
---------------

Create missing image renditions and delete obsolete ones. This is useful
after changing image slot dimension settings or adding new image formats.

.. code-block:: bash

    # Sync renditions for all posts
    python manage.py sync_renditions

    # Sync renditions for a specific post
    python manage.py sync_renditions --post-slug my-post-slug

    # Sync renditions for all posts in a blog
    python manage.py sync_renditions --blog-slug my-blog-slug

Options:

``--post-slug SLUG``
    Only sync renditions for the post with this slug.

``--blog-slug SLUG``
    Only sync renditions for posts belonging to this blog. The slug must
    resolve to exactly one blog; missing or ambiguous slugs raise
    ``CommandError`` instead of selecting an arbitrary match.

Video Management
================

recalc_video_posters
--------------------

Regenerate poster images for all videos from the video files. Requires
``ffmpeg`` to be installed.

.. code-block:: bash

    python manage.py recalc_video_posters

This command takes no options.

Media Backup and Restore
========================

These commands require Django >= 4.2 and both ``production`` and ``backup``
storage backends to be configured in your ``STORAGES`` setting. See
:doc:`../reference/settings` for storage configuration details.

media_backup
------------

Copy all media files from production storage to backup storage. Only files
not already present in the backup are copied.

.. code-block:: bash

    python manage.py media_backup

media_restore
-------------

Restore media files from backup storage to production storage. Only files
not already present in production are copied.

.. code-block:: bash

    python manage.py media_restore

media_replace
-------------

Replace specific files on production storage with versions from the local
filesystem. Useful when you have a better-compressed version of a video
but want to keep the same filename. Requires Django >= 4.2 and configured
``production`` and ``backup`` storage backends.

.. code-block:: bash

    python manage.py media_replace path/to/video1.mp4 path/to/video2.mp4

Arguments:

``paths``
    One or more file paths to replace on production storage.

media_sizes
-----------

Print the sizes of all media files on the production storage backend,
categorized by type (video, image, other) with totals in MB. Requires
Django >= 4.2 and configured ``production`` and ``backup`` storage backends.

.. code-block:: bash

    python manage.py media_sizes

media_stale
-----------

Find media files in production storage that are not referenced by any
database record. The command checks paths referenced by image, video,
audio, transcript, and file records before classifying anything as stale.
Requires Django >= 4.2 and configured ``production`` and ``backup``
storage backends.

.. code-block:: bash

    # Show stale files
    python manage.py media_stale

    # Show and delete stale files
    python manage.py media_stale --delete

Options:

``--delete``
    Delete the stale files instead of only listing them.

Reference Site
==============

ensure_reference_site
---------------------

Create or update a reference site with demo blog and podcast content.
Useful for testing themes and development.

.. code-block:: bash

    # Create with default theme
    python manage.py ensure_reference_site

    # Create with a specific theme
    python manage.py ensure_reference_site --theme bootstrap5

    # Pull real media from production for realistic demos
    python manage.py ensure_reference_site --remote-media

    # Delete and recreate from scratch
    python manage.py ensure_reference_site --reset

    # Also generate image renditions
    python manage.py ensure_reference_site --with-renditions

Options:

``--theme SLUG``
    Theme slug to use. Defaults to the first available styleguide theme
    (preferring bootstrap5, bootstrap4, plain in that order).

``--remote-media``
    Pull real images and audio from production URLs configured via
    ``CAST_STYLEGUIDE_*`` settings for better-looking demos.

``--reset``
    Delete existing reference site data before recreating.

``--with-renditions``
    Generate missing image renditions while creating content.

styleguide_prefetch
-------------------

Prefetch styleguide demo data and optionally build gallery renditions.

.. code-block:: bash

    python manage.py styleguide_prefetch
    python manage.py styleguide_prefetch --theme bootstrap5 --with-renditions

Options:

``--theme SLUG``
    Theme slug to render for. Defaults to the first available styleguide
    theme (preferring bootstrap5, bootstrap4, plain in that order).

``--with-renditions``
    Generate missing renditions while prefetching.
