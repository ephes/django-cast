############
Installation
############

Django Cast can be installed as a standalone project or integrated into an existing Django application.

**************
Prerequisites
**************

Before you begin, ensure you have:

- Python 3.11 or higher
- `uv <https://docs.astral.sh/uv/>`_ (recommended) or pip
- `ffmpeg <https://ffmpeg.org/download.html>`_ (optional, for video/audio processing)

******************
New Project Setup
******************

The fastest way to start with django-cast is using the ``django-cast-quickstart`` command:

.. code-block:: shell

    # Create a new directory for your project
    mkdir myproject
    cd myproject

    # Create virtual environment and install django-cast
    uv venv
    uv pip install django-cast

    # Create a new django-cast project
    uv run django-cast-quickstart mysite

This command will:

1. Create a complete Django project structure
2. Configure all required settings
3. Run database migrations
4. Collect static files (including JavaScript for galleries and audio players)
5. Create a superuser account (username: ``user``, password: ``password``)
6. Start the development server
7. Open your browser to the Wagtail admin interface

.. warning::
   The default credentials (``user``/``password``) are for development only.
   Always change them before deploying to production!

Command Options
===============

The quickstart command supports several options:

.. code-block:: shell

    # Default: Creates superuser with user/password
    uv run django-cast-quickstart mysite

    # Prompt for custom superuser credentials
    uv run django-cast-quickstart mysite --interactive-superuser

    # Skip superuser creation
    uv run django-cast-quickstart mysite --no-superuser

After Quickstart
================

Once the server is running, you can:

1. **Access the Wagtail admin** at http://localhost:8000/cms/
2. **Access the Django admin** at http://localhost:8000/admin/
3. **View your site** at http://localhost:8000/

***********************************
Integrating Into Existing Projects
***********************************

This section explains how to add django-cast to an existing Django project.

.. note::
   If you're starting a new project, use the quickstart method above instead,
   which automates most of these steps.

Installation
============

Install django-cast in your virtual environment:

.. code-block:: shell

    pip install django-cast
    # or with uv
    uv pip install django-cast

Configure Django
================

Settings
--------

Add the required apps and middleware to your Django settings:

.. code-block:: python

   # settings.py
   from cast import CAST_APPS, CAST_MIDDLEWARE

   INSTALLED_APPS = [
       # Your existing Django apps...
       "django.contrib.admin",
       "django.contrib.auth",
       "django.contrib.contenttypes",
       "django.contrib.sessions",
       "django.contrib.messages",
       "django.contrib.staticfiles",
       "django.contrib.sites",  # Required by django-cast
   ] + CAST_APPS  # Adds all django-cast required apps

   MIDDLEWARE = [
       # Your existing middleware...
       "django.middleware.security.SecurityMiddleware",
       "django.contrib.sessions.middleware.SessionMiddleware",
       "django.middleware.common.CommonMiddleware",
       "django.middleware.csrf.CsrfViewMiddleware",
       "django.contrib.auth.middleware.AuthenticationMiddleware",
       "django.contrib.messages.middleware.MessageMiddleware",
       "django.middleware.clickjacking.XFrameOptionsMiddleware",
   ] + CAST_MIDDLEWARE  # Adds Wagtail and other required middleware

.. note::
   ``CAST_APPS`` includes: cast, wagtail and its dependencies, django-allauth,
   django-crispy-forms, and other required packages.

   ``CAST_MIDDLEWARE`` includes: Wagtail middleware, django-allauth middleware,
   and django-threadlocals.

Required Settings
-----------------

Add these essential settings:

.. code-block:: python

   # Wagtail settings
   WAGTAIL_SITE_NAME = "My Site"
   WAGTAILADMIN_BASE_URL = "http://localhost:8000"

   # Site ID for django.contrib.sites
   SITE_ID = 1

   # Authentication (using django-allauth)
   AUTHENTICATION_BACKENDS = [
       "django.contrib.auth.backends.ModelBackend",
       "allauth.account.auth_backends.AuthenticationBackend",
   ]

   # Login URLs
   LOGIN_URL = "/login/"
   LOGIN_REDIRECT_URL = "/"

   # Media files (user uploads)
   MEDIA_ROOT = BASE_DIR / "media"
   MEDIA_URL = "/media/"

   # Wagtail image model
   WAGTAILIMAGES_IMAGE_MODEL = "cast.Image"

Optional Settings
-----------------

Configure additional features as needed:

.. code-block:: python

   # Image renditions
   CAST_IMAGE_FORMATS = ["jpeg", "avif"]  # Modern image formats

   # Responsive image sizes
   CAST_REGULAR_IMAGE_SLOT_DIMENSIONS = {
       "300": "300",
       "600": "600",
       "1200": "1200",
   }

   # Comments
   COMMENTS_APP = "cast.comments"
   CAST_COMMENTS_EXCLUDE_FIELDS = ("email", "url", "title")

URL Configuration
=================

Update your main URL configuration:

.. code-block:: python

   # urls.py
   from django.contrib import admin
   from django.urls import include, path
   from django.conf import settings
   from django.conf.urls.static import static
   from cast import cast_and_wagtail_urls

   urlpatterns = [
       path("admin/", admin.site.urls),
       path("", include(cast_and_wagtail_urls)),  # Includes all Cast and Wagtail URLs
   ]

   if settings.DEBUG:
       urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

Database Setup
==============

Create and run migrations:

.. code-block:: shell

   python manage.py migrate
   python manage.py createsuperuser

Static Files
============

django-cast includes JavaScript for galleries and audio players. Collect static files:

.. code-block:: shell

   python manage.py collectstatic

Create Initial Content
======================

1. Start the development server:

   .. code-block:: shell

      python manage.py runserver

2. Log into the Wagtail admin at http://localhost:8000/cms/
3. Delete any default pages
4. Create a **HomePage** at the root
5. Create a **Blog** as a child of the HomePage

Advanced Integration
====================

Custom Templates
----------------

Override Cast templates by creating your own in your project's template directory:

.. code-block:: text

   templates/
   └── cast/
       ├── blog_list_page.html
       ├── post.html
       └── ...

Custom Settings Module
----------------------

For complex projects, create a separate settings module:

.. code-block:: python

   # settings/cast.py
   # All django-cast specific settings
   CAST_IMAGE_FORMATS = ["jpeg", "avif"]
   # ... other Cast settings

   # settings/__init__.py
   from .base import *
   from .cast import *

Testing the Integration
-----------------------

Verify your installation:

.. code-block:: python

   # Check if models are available
   python manage.py shell
   >>> from cast.models import Blog, Post
   >>> Blog.objects.all()

*************************
Next Steps
*************************

Creating Your First Blog
========================

1. Log into the Wagtail admin
2. Navigate to **Pages** in the sidebar
3. Click **Add child page** at the root level
4. Choose **Blog** as the page type
5. Fill in the blog details and publish

Creating Your First Post
========================

1. Navigate to your blog page in the admin
2. Click **Add child page**
3. Choose **Post** as the page type
4. Add your content using the rich text editor
5. Optionally add images, galleries, or audio/video
6. Publish your post

Further Configuration
=====================

- Customize templates in ``templates/cast/``
- Configure additional settings (see :doc:`reference/settings`)
- Set up a production database (PostgreSQL recommended)
- Configure media file storage for production (see :doc:`media/overview`)
- Deploy to your hosting provider (see :doc:`operations/deployment`)
