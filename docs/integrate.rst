###################################
Integrating Into Existing Projects
###################################

This guide explains how to add django-cast to an existing Django project.

.. note::
   If you're starting a new project, consider using the :doc:`quickstart` guide instead,
   which automates most of these steps.

************
Installation
************

Install django-cast in your virtual environment:

.. code-block:: shell

    pip install django-cast
    # or with uv
    uv pip install django-cast

****************
Configure Django
****************

Settings
========

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
   ] + CAST_MIDDLEWARE  # Adds django-cast specific middleware

Required Settings
=================

Add these required settings to your ``settings.py``:

.. code-block:: python

    # Site framework
    SITE_ID = 1

    # Media files
    MEDIA_ROOT = BASE_DIR / "media"
    MEDIA_URL = "/media/"

    # Comments configuration
    COMMENTS_APP = "fluent_comments"
    FLUENT_COMMENTS_EXCLUDE_FIELDS = ("email", "url", "title")
    CAST_COMMENTS_ENABLED = True  # Set to False to disable comments

    # Crispy forms (for Bootstrap 4 styling)
    CRISPY_TEMPLATE_PACK = "bootstrap4"
    CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap4"

    # Wagtail
    WAGTAIL_SITE_NAME = "My Site"

    # Django Vite configuration for JavaScript assets
    DJANGO_VITE = {
        "cast": {
            "dev_mode": False,
            "static_url_prefix": "cast/vite/",
            "manifest_path": BASE_DIR / "static" / "cast" / "vite" / "manifest.json",
        }
    }

URL Configuration
=================

Update your main URL configuration:

.. code-block:: python

    # urls.py
    from django.conf import settings
    from django.contrib import admin
    from django.urls import path, include
    from wagtail import urls as wagtail_urls
    from wagtail.admin import urls as wagtailadmin_urls
    from wagtail.documents import urls as wagtaildocs_urls

    urlpatterns = [
        # Django admin (optional if you prefer Wagtail admin)
        path("admin/", admin.site.urls),

        # Wagtail admin
        path("cms/", include(wagtailadmin_urls)),

        # Wagtail documents
        path("documents/", include(wagtaildocs_urls)),

        # Cast URLs (blog, API endpoints)
        path("cast/", include("cast.urls", namespace="cast")),

        # Comments
        path("comments/", include("fluent_comments.urls")),

        # Wagtail pages (place last as it matches everything)
        path("", include(wagtail_urls)),
    ]

    if settings.DEBUG:
        from django.conf.urls.static import static
        from django.contrib.staticfiles.urls import staticfiles_urlpatterns

        # Serve static and media files from development server
        urlpatterns += staticfiles_urlpatterns()
        urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

********************
Database Setup
********************

Run migrations to create the necessary database tables:

.. code-block:: shell

    python manage.py migrate
    python manage.py collectstatic --noinput

Create a superuser if you don't already have one:

.. code-block:: shell

    python manage.py createsuperuser

********************
Template Integration
********************

django-cast uses template inheritance. You may want to:

1. Create a ``base.html`` template that django-cast templates can extend
2. Override django-cast templates by creating files with the same path in your project

Example base template structure:

.. code-block:: django

    {# templates/base.html #}
    <!DOCTYPE html>
    <html>
    <head>
        <title>{% block title %}{% endblock %} - {{ settings.WAGTAIL_SITE_NAME }}</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
        {% block extra_css %}{% endblock %}
    </head>
    <body>
        {% block content %}{% endblock %}
        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
        {% block javascript %}{% endblock %}
    </body>
    </html>

*********************
Optional Dependencies
*********************

- **ffmpeg**: Required for video poster extraction and audio duration detection
- **PostgreSQL**: Recommended for production (though SQLite works for development)

*************
Verification
*************

1. Start your development server: ``python manage.py runserver``
2. Visit http://localhost:8000/cms/ to access the Wagtail admin
3. Create a Blog page as a child of your site's root page
4. Create Post pages as children of your Blog

****************
Troubleshooting
****************

JavaScript/Vite Errors
======================

If you see errors about missing Vite assets:

1. Ensure you ran ``python manage.py collectstatic``
2. Check that ``DJANGO_VITE`` is configured correctly
3. For development, you can set ``"dev_mode": True`` in ``DJANGO_VITE``

Missing Apps Errors
===================

If you get import errors, ensure all required apps are installed:

- All apps from ``CAST_APPS`` must be in ``INSTALLED_APPS``
- ``django.contrib.sites`` is required and often forgotten

Template Not Found
==================

django-cast looks for templates in this order:

1. Your project's templates directory
2. App template directories
3. django-cast's built-in templates

Ensure your ``TEMPLATES`` setting includes ``'APP_DIRS': True``.
