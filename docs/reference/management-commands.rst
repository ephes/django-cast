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
level: Django settings or environment variables. The API base URL is always
deployment configuration; the Wagtail admin transcript workflow can
additionally use a site-scoped API token for editor-triggered jobs.
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

If two selected episodes share one audio object, the command stops before
submitting any jobs. Select a single episode for that audio to use its context,
or select the audio directly with ``--audio-id`` without those episode IDs.
Repeating the same ``--episode-id`` generates at most one transcript.
The command checks for a complete transcript on the writer database when each
audio target reaches its turn. Use ``--force`` to bypass that check.
If selected audio disappears before its turn, the command reports that audio
ID as a failed target, processes the remaining targets, and exits with an error.

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
    exist for the selected audio object. This bypasses the old artifacts'
    completeness read, so it can recover malformed stored JSON.

Without ``--force``, malformed JSON or non-object Podlove/DOTe data counts as
incomplete and is regenerated. A Voxhelm failure is reported for that audio;
other targets continue, and the command exits with an error after the summary.

The command prints per-audio status lines and a final summary in the form
``processed=<n> created=<n> updated=<n> skipped=<n> errors=<n>``.

import_transcript_glossary
--------------------------

Load transcript glossary terms for one podcast from a JSON file, a list of
``{"term", "variants", "notes"}`` objects (``variants`` as a list or a
newline-separated string). Existing terms are matched ignoring case and
updated; entries that fail validation are skipped and reported on stderr. See
:ref:`transcript_glossary` for the format and the validation rules.

Numeric podcast IDs are checked against the field range of the write database
used to look up the podcast.

.. code-block:: bash

    python manage.py import_transcript_glossary my-podcast glossary.json --dry-run

Options:

``--dry-run``
    Validate and report without saving.

In-place input changes visible in the file's size or modification/change time are
refused before writes, including in dry runs (best effort on coarse filesystem clocks).
Symlinks and atomic pathname replacements retain the coherent opened generation.
Entries containing lone Unicode surrogates or NUL in a term, variant or note
are skipped before row validation and reported by entry number and field.

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
    A transcript id; repeat for several. Before accessing artifacts, the command
    checks that each selected transcript's read and write routes match the
    database it was loaded from. This also applies in dry runs.

``--podcast ID_OR_SLUG``
    The transcripts of the podcast's episodes, selected on the podcast's database.
    Incompatible read/write routing is refused before artifact access.

``--all``
    Read transcripts in batches of up to 100, through the highest ID visible
    when the command starts. Higher IDs are picked up on a later run.

``--dry-run``
    Compute and report without writing.

Each successful refresh prints a line
``transcript <id>: <status> automatic=<n> approved=<n> proposals=<n> changed=<n>``,
where ``status`` is ``applied``, ``needs_episode`` (the audio is used by several
episodes, or the stored episode no longer uses it; an editor must choose) or
``no_segments``, and ``changed`` counts Podlove segments whose text changed.
For each failed refresh, the command reports the transcript ID and, when safe,
the exception type on stderr. It processes the remaining transcripts, then
exits with an error that includes the failure count.

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
same thumbnail specs, including all focal-point variants of each obsolete key.
Uploaded originals, Wagtail admin renditions, and custom site renditions with
unrelated filter specs are preserved.

The command also checks that each required rendition's stored file still
exists, and regenerates the file for rows whose file was lost. Only this
command checks stored files. Publication and gallery rendition creation
compare database rows. The command discovers post images and loads repair
images in batches, preserving every
role of a shared image. Before it deletes an obsolete rendition, it rechecks
the source and the exact verified replacement on the writer database.
A changed pair is reported as a conflict and its old rendition is retained.
Rerun the command to reconcile the current files.

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

The command resolves ``--blog-slug`` once and uses that blog throughout the run,
even if its slug is renamed after selection.

Options:

``--post-slug SLUG``
    Only sync renditions for posts with this slug. When combined with
    ``--blog-slug``, only matches in that blog's subtree are selected.

``--blog-slug SLUG``
    Only sync renditions for posts belonging to this blog. The slug must
    resolve to exactly one blog; missing or ambiguous slugs raise
    ``CommandError`` instead of selecting an arbitrary match. The blog is
    validated first, including when ``--post-slug`` is also supplied. Any
    explicitly empty selection raises ``CommandError`` before media changes.

All planned missing replacements are generated and their saved rows/files
verified before any obsolete counterpart is retired. A generation or storage
failure rolls back that image's rows and keeps old counterparts for a safe retry.
Each repair and new rendition uses a fresh storage key. After rollback, only
acknowledged operation-owned files without a surviving row are removed. Cleanup
diagnostics are best effort. The cleanup continues checking remaining files
even if a logging handler fails, and the original failure is raised. If storage
changes a requested name, ownership is uncertain: the returned key is logged and retained
for inspection. An uncertain failed save that returns no name cannot be cleaned
automatically. Successfully committed earlier images remain and are reused on
retry. Unrelated rendition specifications are preserved.

Repair cache invalidation runs after the outermost transaction commits on the
writer database, so a reader refilling the old row before commit cannot leave
that entry cached afterward. A rollback queues no purge. Verification inside
the command reads writer rows directly rather than shared cache entries.

A cache callback failure reports ``committed ... cache purge pending`` with the
database alias, image ID, rendition ID and stored name. These replacement rows
and bytes are already committed; do not delete them or regenerate the image.
Django stops later commit callbacks after a failure, so retry invalidation for
**all** renditions of the reported image on that alias, for example in
``manage.py shell`` (substitute the reported alias and synthetic example ID):

.. code-block:: python

    from wagtail.images.models import Rendition

    for rendition in Rendition.objects.using("default").filter(image_id=123):
        rendition.purge_from_cache()

Retry after restoring cache connectivity, then rerun ``sync_renditions`` to
finish any remaining images and obsolete-counterpart retirement. Inventory
alone cannot identify a pending cache purge. Library callers of
``repair_missing_rendition_files`` own the transaction and rollback receipt.
By default (publication, gallery and style-guide rendition preparation) a
purge failure is logged at ERROR with the same recovery identifiers and does
not fail the already committed caller or stop its later commit callbacks.
Passing ``strict_cache_invalidation=True`` (as ``sync_renditions`` does) raises
``RenditionCacheInvalidationError`` instead, which distinguishes
committed/cache-pending repair from a failed writer transaction. For nested transactions the outer owner must
retain the receipt until commit or rollback, since Django has no rollback hook.

Video Management
================

recalc_video_posters
--------------------

Regenerate poster images for all videos from the video files. Requires
``ffmpeg`` to be installed. The command keeps going if one video fails and
prints a final ``processed=<n> errors=<n>`` summary. It counts and scans videos
on the write database selected by Django's router for ``Video`` and publishes
posters on that same database. The scan fetches rows in primary-key order in
batches, with a single count for the progress display.

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

Every missing-object copy must be saved under exactly the requested key.
A backend returning a generated name makes the copy fail; only that newly saved
alternate is removed. An object created concurrently at the requested path is
kept. Inventory paths use forward-slash separators on every platform, preserving
literal characters within storage keys.
Use storage backends that preserve requested names for backup and restore.

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
    with equal sizes is downloaded from both storages on each run, which
    costs time and transfer on remote storage. Unchanged files are not
    rewritten. For changed files, staging verification reads the source again
    and reads the staged target bytes. A digest mismatch refuses publication.
    Each full read has its own 16 GiB byte ceiling and a 300 second
    deadline that grows with the object size (at most about 68 minutes);
    exceeding it reports an incomplete path without publishing a replacement.
    See :doc:`../operations/backup` for inventory limits, synchronous I/O
    limitations and the same-host publication concurrency contract.

    A changed file is first copied to a temporary key next to the target
    (``<path>.django-cast-refresh-<random>.tmp``) in the backup storage, and
    the existing backup copy is only overwritten from that complete staged
    copy. The existing copy is never deleted first. If production cannot be
    read, the staged copy cannot be written, or the backup storage stores the
    new bytes under a generated name instead of overwriting (Django's
    ``FileSystemStorage`` without ``allow_overwrite``, or S3 storage with
    ``file_overwrite = False``), the previous backup copy is kept, the generated
    copy is removed, and the path is reported as an error. A staged copy is
    verified against the source SHA-256 digest before the final write. Failed
    or incomplete staging is removed. A same-name save is followed by a
    SHA-256 read of the final key. If this read fails or the digest differs,
    the path is reported as an error and the verified stage is retained for
    recovery. A final overwrite that raises also retains the stage. A save
    under a generated name keeps no stage.
    Verified publication removes its stage. Cleanup attempts every other
    requested and returned staging name even if another deletion fails. Leftover
    names and deletion failures are logged and reported on command stderr when publication has
    already failed, preserving the original publication exception; cleanup failure
    after successful publication is itself an error. Inspect the reported keys
    and remove recoverable leftovers manually.

    The final overwrite itself is only as safe as the backup storage backend
    makes it. Object storage replaces an object atomically, so a failed
    overwrite keeps the previous object. A backend that writes in place
    (``FileSystemStorage`` with ``allow_overwrite``) can leave a partial file
    under the path if that last write fails. If the source remains available,
    rerun ``media_backup --refresh-changed`` to repair it. If the source is gone,
    open/download the reported complete recovery key through the configured
    target Storage, inspect it, and explicitly save its bytes to the intended
    destination with an overwrite-capable backend. Verify the destination
    digest before deleting the recovery key with ``Storage.delete(key)``.
    Retried commands do not automatically consume or delete older recovery keys.
    Missing-copy writes are also staged. When a write raises or final
    verification fails, their final keys and stages are cleaned under the
    same-host publisher lock; no recovery stage is kept because an ordinary
    retry copies the file again. A run that is
    killed can leave a staged ``.tmp`` key on storage. Backup and restore skip and
    report reserved media staging keys. Inspect and remove abandoned objects
    manually.

    With this option the command prints
    ``copied=<n> refreshed=<n> unchanged=<n> errors=<n>``. A path that cannot be
    checked, copied, compared or refreshed does not stop the run, but the
    command then exits with ``CommandError`` (a non-zero exit status). Without
    the option failed paths are also reported and processing continues.

Backup and restore reserve keys ending in
``.django-cast-refresh-<32 lowercase hexadecimal characters>.tmp`` for temporary
sync and replacement data. Backup and restore also recognize legacy
``.django-cast-replace-<32 lowercase hexadecimal characters>.tmp`` keys. Both
patterns allow Django-generated ``_<alphanumeric>`` suffixes before ``.tmp``.
If a backend returns an unreserved staging name, publication fails and cleanup
attempts to remove the stage. Reserved source keys are skipped in every sync
mode and reported by name. They remain on the source storage. Similar names outside this precise pattern remain
ordinary media. Inspect leftovers before removing them manually; arbitrary
backend-renamed temporary keys from older versions require manual inspection too.

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
key before the target path is written. Replacement and sync share the reserved
``.django-cast-refresh-<32 lowercase hexadecimal characters>.tmp`` suffix
described above. Backup and restore inventory also skips legacy
``.django-cast-replace-<32 lowercase hexadecimal characters>.tmp`` keys and
reports the excluded keys on stderr. The command verifies the staged bytes against the local file
and reopens the published object to verify its bytes before reporting success.
Each SHA-256 read uses the same 16 GiB ceiling and size-scaled deadline as
media backup. For existing production files, the command only reports success
when the storage backend saves back to the exact
requested path; if the backend auto-generates a different name, the generated
file is removed, the original path is left untouched, and the path is reported
as an error.

A failed replacement does not stop the run: the remaining paths are still
attempted. If the published object cannot be read back or its bytes differ,
the command reports the verified staging key it retained for recovery.
Inspect that key before retrying or deleting it manually. Other staging keys
are cleaned up, including partial writes whose save failed before returning a
name. Cleanup failures are reported separately. After printing the summary, the
command exits with ``CommandError`` (a non-zero exit status) when at least one
replacement failed, even if others succeeded, so automation can detect a
partial run. Skipped paths and ``--dry-run`` do not affect the exit status.

media_sizes
-----------

Print the sizes of all media files on the production storage backend,
categorized by type (video, image, misc) with totals in MiB (bytes / 2**20). Requires configured
``production`` and ``backup`` storage backends.

.. code-block:: bash

    python manage.py media_sizes

The built-in categories are extension-based:

- video: ``.mov``, ``.mp4``
- image: ``.jpg``, ``.jpeg``, ``.png``
- misc: everything else

Extensions are matched case-insensitively. Nested production directories are
included; the backup store is not traversed. The command reads directory listings
and byte sizes only, without opening, saving or deleting objects. Storage failures
propagate instead of producing a successful partial report. An empty store reports
zero for all categories and the total.

media_stale
-----------

Find media files in production storage that are not referenced by any
database record. The command checks paths referenced by image, video,
audio, transcript and contributor voice-reference records before classifying
anything as stale. For django-cast models, this scan reads only the stored
file-name columns. Only known django-cast/Wagtail-managed media prefixes are
eligible for stale reporting or deletion, so unrelated objects in the same
storage backend are ignored by default. Leftover uploads of the removed
``File`` model under ``cast_files/`` are no longer reported.
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
The age boundary is inclusive. The command completes the storage listing
before requesting sizes and only requests sizes for stale candidates.
An incomplete listing aborts the command before any deletion.
Configure the age setting in your project settings::

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
    Replace only the designated ``styleguide-blog`` and ``styleguide-podcast``
    roots directly below the selected Site's root page, including their descendants.
    The selected Site is the first Site, as in the styleguide builder. Each existing
    root must have the expected page type and belong to the ``styleguide`` seed user;
    duplicate roots, another owner or a different page type cause refusal before
    any media is prepared or any page is deleted. Matching slugs elsewhere in the
    page tree are preserved and are not reused by the builder.

    Media (including any remote fetch) is prepared and committed before the page
    transaction starts, so no page locks are held during remote downloads. Root
    checks, deletion, content creation and context preparation share one database
    transaction: a failed rebuild restores the old reference pages and their
    identities. Content creation and context preparation still write to storage
    inside that transaction (the Podlove transcript file and, with
    ``--with-renditions``, image renditions).
    Prepared media rows and files stay in place after a failed rebuild; storage
    side effects are not undone.

``--with-renditions``
    Generate missing preview gallery renditions for this invocation.

Without these flags, the command uses the configured remote-media and rendition
settings.

On success, the command prints the resolved blog and podcast URLs plus a post
count summary scoped to the created reference blog.

Reference seed concurrency
~~~~~~~~~~~~~~~~~~~~~~~~~~

The styleguide view and ``ensure_reference_site`` reserve the stable Wagtail
root row before looking up or creating reference pages. This also obtains the
SQLite writer reservation before any seed read snapshot; PostgreSQL writers
serialize on the same root. Reset rechecks ownership after admission. User
setup uses a separate short reservation; remote downloads and media preparation
run before the page transaction and hold no seed writer lock.


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
    Generate missing preview gallery renditions for this invocation. An
    invocation without the flag and ordinary styleguide requests use their
    configured ``CAST_STYLEGUIDE_GENERATE_RENDITIONS`` value, including while
    the command is running.

On success, the command prints ``Styleguide prefetch complete for theme
'<theme>'``.
