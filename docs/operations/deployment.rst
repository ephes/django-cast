.. _deployment_overview:

**********
Deployment
**********

This section covers key considerations for deploying Django Cast in production.

Prerequisites
=============

- Python 3.11+
- A database (PostgreSQL or SQLite)
- A reverse proxy (e.g., Traefik, Nginx) with a WSGI server (e.g., Gunicorn)

Basic Configuration
===================

Your production settings should include:

.. code-block:: python

    DEBUG = False
    ALLOWED_HOSTS = ["your-domain.com"]
    SECRET_KEY = os.environ["SECRET_KEY"]  # never hardcode

    # Wagtail
    WAGTAILADMIN_BASE_URL = "https://your-domain.com"

See :doc:`../installation` for the full ``INSTALLED_APPS``, ``MIDDLEWARE``,
and URL configuration.

Keep dev-only routes disabled in production unless you explicitly need them:

.. code-block:: python

    CAST_ENABLE_DEV_TOOLS = False

Application Server
==================

A typical production setup uses Gunicorn behind a reverse proxy:

.. code-block:: bash

    gunicorn --workers 4 --timeout 600 --bind 127.0.0.1:8000 config.wsgi:application

Manage the process with systemd for automatic restarts and logging.

Transcript Worker
=================

If the site enables Voxhelm transcript generation from Wagtail admin, run a
Django Tasks database worker in addition to the web process. Install the
optional ``transcript-worker`` extra first; it requires a Wagtail/django-tasks
combination compatible with ``django-tasks-db`` 0.12. Wagtail 7.0 LTS uses
``django-tasks`` 0.7 and is not compatible with that database backend.

.. code-block:: bash

    uv pip install "django-cast[transcript-worker]"

.. code-block:: bash

    python manage.py db_worker --backend cast_transcripts --worker-id homepage-transcripts

Use a distinct ``--worker-id`` per deployed site, for example
``python-podcast-transcripts`` for a second site sharing the same codebase.
The default task backend should remain immediate; only the
``cast_transcripts`` backend should point at ``django_tasks_db.DatabaseBackend``.
``python manage.py check`` reports ``cast.E009`` when Voxhelm credentials
resolve from Django settings or the environment but ``settings.TASKS`` has no
``cast_transcripts`` entry. django-cast resolves that backend before submitting a
transcription job, so a missing entry makes transcript generation fail
immediately with a configuration message instead of leaving a queued generation
behind an unfinished remote job. The check reads only Django settings and
environment variables, because the site-scoped Wagtail ``Voxhelm settings``
require database access; configure the backend even when the API token lives
only in Wagtail admin.
The web process and transcript worker must both receive the Voxhelm
configuration used for job submission and artifact downloads. For
deployment-managed secrets, set ``CAST_VOXHELM_API_BASE`` and
``CAST_VOXHELM_API_KEY`` in the shared process environment. The API base URL is
always deployment configuration (it is no longer a Wagtail site setting); a
token stored in Wagtail ``Voxhelm settings`` overrides only the key. To switch
a site to the deployment key, tick "Remove stored API token" in Wagtail.
When upgrading past the migration that removed the site-level API base
(``cast.0088``), set ``CAST_VOXHELM_API_BASE`` in deploy config first: the
migration logs a warning for every stored site base that differs from it.
If ``CAST_VOXHELM_DIARIZATION_ENABLED`` is enabled, make sure the Voxhelm
backend has diarization support configured. Full-episode diarization can be
slow and CPU-heavy, so keep it on the queued transcript worker path instead of
waiting for completion in a Wagtail admin request.

Static Files
============

Django Cast ships pre-built JavaScript assets (image gallery, Podlove audio
player). Collect all static files before deployment:

.. code-block:: bash

    python manage.py collectstatic --noinput

Serve the ``STATIC_ROOT`` directory via your reverse proxy, a storage backend,
or a CDN.

Media Storage
=============

Uploaded media (images, audio, video) is stored via Django's
``STORAGES["default"]`` backend. A common production setup uses an object
store like AWS S3 with CloudFront as CDN.

See :ref:`cdn_configuration` in the Settings reference for S3 + CloudFront
configuration details.

.. important::

    Set ``DELETE_WAGTAIL_IMAGES = False`` when using S3. This prevents
    your development environment from accidentally deleting production images.

If you use automatic media processing features in production, make sure the
required FFmpeg tools are installed on your application hosts:

- ``ffprobe`` for audio duration extraction, chapter-mark import, and video dimension detection
- ``ffmpeg`` for video poster generation

Editor, legacy API, and Wagtail admin audio/video uploads share a per-user
upload lock stored in Django's default cache. Multi-worker deployments need a
shared cache backend, such as Redis or Memcached, for that lock to coordinate
requests across processes; ``LocMemCache`` only coordinates within one process.

Media is served by the storage backend or web server, not by django-cast, so
response headers for user uploads are a deployment concern. Serve media from a
separate origin where possible, and at least send
``X-Content-Type-Options: nosniff`` for all media plus
``Content-Disposition: attachment`` for generic file uploads under
``cast_files/``. django-cast rejects SVG image uploads and limits generic files
to ``CAST_FILE_EXTENSIONS``, but headers keep older stored files inert as well.
For example, with nginx:

.. code-block:: nginx

    location /media/ {
        add_header X-Content-Type-Options nosniff always;
    }
    location /media/cast_files/ {
        add_header X-Content-Type-Options nosniff always;
        add_header Content-Disposition attachment always;
    }

For backup and restore of media files, see :doc:`backup` and the
:ref:`media management commands <cast_management_commands>`.

Database
========

Run migrations before starting the application:

.. code-block:: bash

    python manage.py migrate

Both PostgreSQL and SQLite are supported. PostgreSQL is the more typical
production choice, especially for multi-server deployments. SQLite can work
for simpler single-server setups, but operational characteristics such as
locking, backups, and write concurrency remain your responsibility.

Image Renditions
================

After initial deployment or after changing image slot dimension settings,
generate image renditions:

.. code-block:: bash

    python manage.py sync_renditions

This creates responsive image variants used by the gallery and post templates.
See :ref:`cast_management_commands` for details.

Example: Ansible-Based Deployment
==================================

A production deployment typically involves:

1. Sync source code to the server (rsync or git clone)
2. Create/update a virtualenv and install dependencies (``uv sync --frozen``)
3. Set environment variables (``SECRET_KEY``, ``DATABASE_URL``, AWS
   credentials, etc.) via your deployment environment or an ``.env`` file
4. Run ``python manage.py migrate``
5. Run ``python manage.py collectstatic --noinput``
6. Run ``python manage.py update_index`` (Wagtail search index)
7. Restart the application service (e.g., ``systemctl restart mysite``)

TLS certificates can be managed automatically via Let's Encrypt with a
reverse proxy like Traefik.

Checklist
=========

- [ ] ``DEBUG = False``
- [ ] ``SECRET_KEY`` set from environment variable
- [ ] ``ALLOWED_HOSTS`` configured
- [ ] ``WAGTAILADMIN_BASE_URL`` set to production domain
- [ ] ``CAST_ENABLE_DEV_TOOLS = False`` unless explicitly required
- [ ] Database configured and migrations applied
- [ ] ``collectstatic`` run
- [ ] Media storage configured (local filesystem or S3)
- [ ] ``DELETE_WAGTAIL_IMAGES = False`` if using S3
- [ ] ``ffprobe`` / ``ffmpeg`` installed if using audio/video processing features
- [ ] Image renditions generated with ``sync_renditions``
- [ ] Reverse proxy with TLS configured
- [ ] Application server (Gunicorn) managed by systemd

Upload lease and failure cleanup
--------------------------------

Audio/video upload admission uses atomic ``cache.add`` with a finite
``CAST_EDITOR_MEDIA_UPLOAD_LOCK_SECONDS`` lease. Use a shared cache in multi-worker
setups. Django's portable cache API cannot atomically compare and delete an owner
value, so leases remain until expiry even after successful or failed uploads.
A repeat upload by that user can receive HTTP 429 until then. The lease is a
bounded admission control, not protection for operations exceeding its lifetime.

Failed ingest cleanup attempts every owned file even when one deletion fails.
Incomplete cleanup is logged and reported with the original ingest error linked;
any surviving row is retained for recovery. It may still reference later files
that cleanup successfully removed. An ingest transaction rollback may already
have removed the row; use the logged field names and storage inventory then.

Nested probe deadlines
----------------------

Nested media probe budgets keep the earliest active deadline. A longer inner
budget cannot extend the caller's remaining time, and a shorter budget applies
only for its scope. Normal and exceptional exits restore the parent deadline;
independent asynchronous contexts keep independent budgets.

Replacement transaction ownership
---------------------------------

``StagedFileReplacementGroup.save_model()`` defers successful ownership transfer
and old-file retirement until the owning transaction commits. Use
``with replacements.rollback_scope(using="default"):`` as the outermost scope
(create the group first), placing any additional ``transaction.atomic()`` blocks
inside it. The scope owns a durable Django transaction and cleans files after
exception or silent rollback; an already-active application transaction is
refused before staging. Use the model's database alias for the scope.
Each group supports one ``save_model()`` attempt; create a fresh group for every
save or retry, and finish staging before calling ``save_model()``.

For manually owned transactions, call ``rollback()`` only after leaving the
owning transaction. It refuses to delete pending files while any transaction on
that alias remains active, because Django's public API cannot mark a particular
outer savepoint rollback-only. Django has no public rollback callback. Calling
only ``save_model()`` inside an unowned outer transaction does not provide storage
rollback cleanup; its owner must retain the group and clean up after rollback.

Replacement publication locks and rereads the stored media row before saving.
Stale loaded ``modified`` timestamps or staged old-file names raise
``FileReplacementConflict``; losing staged files are removed. Editor audio
requests receive ``409 media_changed`` and admin forms request a reload. Bulk
writers that bypass model timestamps must implement their own generation checks.
No model schema, theme context, or required setting changes are needed.
