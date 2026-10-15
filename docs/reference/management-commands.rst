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
  ``CAST_VOXHELM_DIARIZATION_ENABLED``, ``CAST_VOXHELM_POLL_INTERVAL``,
  ``CAST_VOXHELM_POLL_TIMEOUT``, ``CAST_VOXHELM_REQUEST_TIMEOUT``

For the management command, configure the API base and key together at one
level: Django settings or environment variables. The Wagtail admin transcript workflow can also use
site-scoped Wagtail settings for editor-triggered jobs.
``CAST_VOXHELM_DIARIZATION_ENABLED`` defaults to ``False``; enable it only when
the Voxhelm backend has diarization configured.
Full-episode diarization can be slow, so prefer the queued Wagtail transcript
worker flow for editor-triggered jobs.

The command honors each selected audio object's
``transcript_diarization_mode``. ``inherit`` uses the global Django or
environment setting above, ``enabled`` requests diarization for that audio, and
``disabled`` omits the diarization payload, speaker-count hint, and diarized
task-reference variant. When targeting an episode, the command keeps the
episode context so enabled diarization can use that episode's contributor count
as the speaker-count hint. Jobs that send known-speaker voice references omit
the hint.

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

import_transcript_glossary
--------------------------

Load transcript glossary terms for one podcast from a JSON file, a list of
``{"term", "variants", "notes"}`` objects (``variants`` as a list or a
newline-separated string). Existing terms are matched ignoring case and
updated; entries that fail validation are skipped and reported on stderr. See
:ref:`transcript_glossary` for the format and the validation rules.

.. code-block:: bash

    python manage.py import_transcript_glossary my-podcast glossary.json --dry-run

Options:

``--dry-run``
    Validate and report without saving.

The command prints a summary in the form
``<podcast>: created=<n> updated=<n> unchanged=<n> skipped=<n>``.

apply_transcript_glossary
-------------------------

Re-apply the transcript glossary to stored transcripts: recompute automatic
replacements and proposals from the raw text in each transcript's private
corrections sidecar with the current glossary, keep editor decisions, and
rewrite the Podlove, DOTe and WebVTT text. Run it after editing glossary terms
or contributor variants. See :ref:`transcript_glossary_corrections`.

.. code-block:: bash

    python manage.py apply_transcript_glossary --podcast my-podcast --dry-run

Options (one of the first three is required):

``--transcript ID``
    A transcript id; repeat for several.

``--podcast ID_OR_SLUG``
    The transcripts of the podcast's episodes.

``--all``
    All transcripts.

``--dry-run``
    Compute and report without writing.

Each transcript prints a line
``transcript <id>: <status> automatic=<n> approved=<n> proposals=<n> changed=<n>``,
where ``status`` is ``applied``, ``needs_episode`` (the audio is used by several
episodes, or the stored episode no longer uses it; an editor must choose) or
``no_segments``, and ``changed`` counts Podlove segments whose text changed.
Failures are reported on stderr, the remaining transcripts are still processed,
and the command then exits with an error.

Image Renditions
================

sync_renditions
---------------

Create missing image renditions. This is useful after changing image slot
dimension settings, adding new image formats, or changing rendition policy such
as ``CAST_GALLERY_THUMBNAIL_RENDITIONS_SRGB``. Because rendition filter specs
are part of Wagtail's rendition keys, enabling or disabling gallery thumbnail
sRGB normalization creates new thumbnail rendition keys; this command creates
the new files and removes the previous/next sRGB-policy counterpart keys for the
same thumbnail specs. Uploaded originals, Wagtail admin renditions, and custom
site renditions with unrelated filter specs are preserved.

Run this as a one-off migration step after a deployment that changes rendition
specifications or policy; it is not required for every normal application
deployment. During an sRGB policy transition, rendering falls back to an
existing predecessor/successor thumbnail rendition until synchronization has
created the requested key.

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

A video counts as failed when creating its poster raises an error (for
example ``ffmpeg`` fails or is missing), when no poster results although one
is wanted (for example the video dimensions cannot be read), or when the video
cannot be saved. Videos that already have a poster, or have poster calculation
switched off, are left as they are and do not count as errors.

If at least one poster could not be recalculated, the command then exits with
``CommandError`` (non-zero status). The other videos have still been
processed and saved, so a failed run is a partial success: fix the reported
videos and run the command again. With no errors, or no videos at all, it
exits successfully.

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

Copy all media files from production storage to backup storage. By default
only files not already present in the backup are copied; a file that exists
under the same path in both storages is never read or compared.

.. code-block:: bash

    # Copy files that are missing in the backup
    python manage.py media_backup

    # Also refresh backup copies whose content differs from production
    python manage.py media_backup --refresh-changed

Options:

``--refresh-changed``
    Also compare every file that exists in both storages and overwrite the
    backup copy when it differs from production. Use this after changing a
    file in place, for example with ``media_replace``: without it the backup
    keeps the bytes it copied first, and a later ``media_restore`` would bring
    back the old file.

    Files are compared by content. Different sizes mark a file as changed
    without reading it; equal sizes prove nothing, so both copies are then read
    completely and their SHA-256 digests compared. Every existing file is
    therefore downloaded from both storages on each run with this option, which
    costs time and transfer on remote storage. Unchanged files are not
    rewritten.

    A changed file is first copied to a temporary key next to the target
    (``<path>.django-cast-refresh-<random>.tmp``) in the backup storage, and
    the existing backup copy is only overwritten from that complete staged
    copy. The existing copy is never deleted first. If production cannot be
    read, the staged copy cannot be written, or the backup storage stores the
    new bytes under a generated name instead of overwriting (Django's
    ``FileSystemStorage`` without ``allow_overwrite``, or S3 storage with
    ``file_overwrite = False``), the previous backup copy is kept, the generated
    copy is removed, and the path is reported as an error. A staged copy is
    removed again whether the refresh succeeds or fails.

    The final overwrite itself is only as safe as the backup storage backend
    makes it. Object storage replaces an object atomically, so a failed
    overwrite keeps the previous object. A backend that writes in place
    (``FileSystemStorage`` with ``allow_overwrite``) can leave a partial file
    under the path if that last write fails; run the command again to repair
    it. A run that is killed can leave a staged ``.tmp`` key in the backup
    storage; remove it before running ``media_restore``.

    With this option the command prints
    ``copied=<n> refreshed=<n> unchanged=<n> errors=<n>``. A path that cannot be
    checked, copied, compared or refreshed does not stop the run, but the
    command then exits with ``CommandError`` (a non-zero exit status). Without
    the option the first storage error still aborts the command.

media_restore
-------------

Restore media files from backup storage to production storage. Only files
not already present in production are copied. ``media_restore`` never
overwrites an existing production file, so it has no ``--refresh-changed``
option.

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
reported as skipped. Replacement files are staged to a temporary production
key before the target path is written. For existing production files, the
command only reports success when the storage backend saves back to the exact
requested path; if the backend auto-generates a different name, the generated
file is removed, the original path is left untouched, and the path is reported
as an error.

A failed replacement does not stop the run: the remaining paths are still
attempted and staged objects are cleaned up. After printing the summary, the
command exits with ``CommandError`` (a non-zero exit status) when at least one
replacement failed, even if others succeeded, so automation can detect a
partial run. Skipped paths and ``--dry-run`` do not affect the exit status.

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
audio, transcript, contributor voice-reference, and file records before
classifying anything as stale. Only known django-cast/Wagtail-managed media
prefixes are eligible for stale reporting or deletion, so unrelated objects in
the same storage backend are ignored by default.
Requires configured ``production`` and ``backup`` storage backends.

.. code-block:: bash

    # Show stale files
    python manage.py media_stale

    # Show and delete stale files
    python manage.py media_stale --delete

Options:

``--delete``
    Delete the stale files under managed media prefixes instead of only listing
    them.

Only files at least ``CAST_MEDIA_STALE_MIN_AGE_DAYS`` old (default: 7 days)
are candidates. The command uses the newest available storage modification or
creation timestamp; a backend without either timestamp leaves the file untouched
and reports its age as unknown. Naive timestamps use the Django default timezone.
The setting must be a non-negative integer; ``0`` removes the age delay.
The age boundary is inclusive. Configure the setting in your project settings::

    CAST_MEDIA_STALE_MIN_AGE_DAYS = 7

Listing remains the default dry run. Before each deletion, the command checks
age again and runs fresh database queries for that exact file name. Files that
became referenced are skipped. No database rows are deleted. This reduces the
race window but cannot make a storage deletion atomic with a concurrent upload
or database write; schedule cleanup when uploads are quiet and retain backups.

The command prints candidate paths, their total size in MB, and counts for
``candidates``, ``deleted``, ``skipped-too-young`` (including unknown ages), and
``skipped-newly-referenced``. The last count applies when using ``--delete``.

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
    Generate missing renditions while prefetching. This turns
    ``CAST_STYLEGUIDE_GENERATE_RENDITIONS`` on for this run only: when the
    command returns or fails, the setting has its previous value again, or is
    unset again if the project does not define it. Calling the command with
    ``call_command`` from a long-running process therefore does not change how
    the styleguide behaves afterwards.

On success, the command prints ``Styleguide prefetch complete for theme
'<theme>'``.
