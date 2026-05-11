.. _cast_management_commands:

*******************
Management Commands
*******************

Django Cast provides several management commands, primarily for managing
media files, image renditions, and reference content.

Transcripts
===========

generate_transcripts
--------------------

Generate or refresh transcript artifacts for specific podcast episodes or
audio objects through a Voxhelm batch transcription job. The command keeps the
existing ``Transcript`` model contract unchanged by storing Podlove JSON,
WebVTT, and DOTe files back onto the model.

For editors, the primary workflow is now in Wagtail admin: episode edit views
and audio edit views expose a ``Generate transcript`` action, and Voxhelm
connection details can be managed in ``Settings -> Voxhelm settings``. The
admin workflow queues completion on the ``cast_transcripts`` Django Tasks
database backend when the optional ``transcript-worker`` extra is installed;
run ``python manage.py db_worker --backend cast_transcripts --worker-id
<site>-transcripts`` alongside the web process. The management command remains
available as operator tooling and fallback automation.

Configuration:

- ``CAST_VOXHELM_API_BASE``: Voxhelm service root or ``/v1`` API base
- ``CAST_VOXHELM_API_KEY``: bearer token for the producer
- optional: ``CAST_VOXHELM_MODEL``, ``CAST_VOXHELM_LANGUAGE``,
  ``CAST_VOXHELM_POLL_INTERVAL``, ``CAST_VOXHELM_POLL_TIMEOUT``,
  ``CAST_VOXHELM_REQUEST_TIMEOUT``

These values can be configured as Django settings, environment variables, or
site-scoped Wagtail settings.

.. code-block:: bash

    # Generate a transcript for one episode
    python manage.py generate_transcripts --episode-id 42

    # Target audio objects directly
    python manage.py generate_transcripts --audio-id 10 --audio-id 11

    # Regenerate even when transcript files already exist
    python manage.py generate_transcripts --episode-id 42 --force

Options:

``--episode-id ID``
    Episode id to transcribe. Can be passed more than once.

``--audio-id ID``
    Audio id to transcribe directly. Can be passed more than once.

``--force``
    Regenerate transcripts even when Podlove, WebVTT, and DOTe files already
    exist for the selected audio object.

The command prints per-audio status lines and a final summary in the form
``processed=<n> created=<n> updated=<n> skipped=<n> errors=<n>``.

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
``ffmpeg`` to be installed. The command keeps going if one video fails and
prints a final ``processed=<n> errors=<n>`` summary.

.. code-block:: bash

    python manage.py recalc_video_posters

This command takes no options.

Media Backup and Restore
========================

These commands require both ``production`` and ``backup`` storage backends to be
configured in your ``STORAGES`` setting. See
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
but want to keep the same filename. Requires configured ``production`` and
``backup`` storage backends.

.. code-block:: bash

    # Preview without writing anything
    python manage.py media_replace path/to/video1.mp4 --dry-run

    # Replace after explicit confirmation
    python manage.py media_replace path/to/video1.mp4 path/to/video2.mp4 --yes

Arguments:

``paths``
    One or more file paths to replace on production storage.

Options:

``--dry-run``
    Preview replacements without writing to production storage.

``--yes``
    Confirm destructive writes. Without this flag, the command prints the
    planned replacements and exits with ``CommandError`` if any real changes
    would have been made.

The command prints summary counters in the form
``planned=<n> replaced=<n> skipped=<n> errors=<n>``. Missing local files are
reported as skipped. If a production delete succeeds but a later save fails,
the command also prints a warning about the data-loss risk for that path.

media_sizes
-----------

Print the sizes of all media files on the production storage backend,
categorized by type (video, image, misc) with totals in MB. Requires configured
``production`` and ``backup`` storage backends.

.. code-block:: bash

    python manage.py media_sizes

The built-in categories are extension-based:

- video: ``.mov``, ``.mp4``
- image: ``.jpg``, ``.jpeg``, ``.png``
- misc: everything else

media_stale
-----------

Find media files in production storage that are not referenced by any
database record. The command checks paths referenced by image, video,
audio, transcript, and file records before classifying anything as stale.
Requires configured ``production`` and ``backup`` storage backends.

.. code-block:: bash

    # Show stale files
    python manage.py media_stale

    # Show and delete stale files
    python manage.py media_stale --delete

Options:

``--delete``
    Delete the stale files instead of only listing them.

The command prints matching stale paths and a final total stale size in MB.

Reference Site
==============

These commands operate on whatever Django project settings module is active.
The examples below use a generic project ``manage.py``. When working in the
django-cast repository itself, use ``uv run python example/manage.py ...`` or
the ``just ensure-reference-site`` / ``just styleguide-prefetch`` wrappers,
because the repository root ``manage.py`` defaults to ``tests.settings``.

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

On success, the command prints the resolved blog and podcast URLs plus a post
count summary for the created reference content.

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

On success, the command prints ``Styleguide prefetch complete for theme
'<theme>'``.
