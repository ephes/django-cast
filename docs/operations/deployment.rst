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
Django Tasks database worker in addition to the web process:

.. code-block:: bash

    python manage.py db_worker --backend cast_transcripts --worker-id homepage-transcripts

Use a distinct ``--worker-id`` per deployed site, for example
``python-podcast-transcripts`` for a second site sharing the same codebase.
The default task backend should remain immediate; only the
``cast_transcripts`` backend should point at ``django_tasks_db.DatabaseBackend``.

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
