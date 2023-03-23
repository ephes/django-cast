############
Installation
############

.. note::
   These instructions presume that you have prior knowledge of
   `virtual environments <https://docs.python.org/3/library/venv.html>`_
   and the `Django <https://https://www.djangoproject.com/>`_ web
   framework. For a more comprehensive guide, refer to
   :doc:`create your first django-cast site<howto/first-cast>`.
   If you want to incorporate django-cast
   into an existing Django project, consult the guide on
   :doc:`integrating django-cast<howto/integrate-cast>` into a
   Django Project.


Install the package with pip in a virtual environment:

.. code-block:: shell

    python -m pip install django-cast

If you don't already have a Django project, you might want to create
one with the following ``django-admin`` command:

.. code-block:: shell

    django-admin startproject mysite


Add following third party apps to your INSTALLED_APPS setting:

.. code-block:: python

   INSTALLED_APPS = (
       ...
       "django.contrib.sites",
       "cast.apps.CastConfig",
       "crispy_forms",
       "crispy_bootstrap4",
       "allauth",
       "allauth.account",
       "allauth.socialaccount",
       "django_filters",
       "django_htmx",
       "rest_framework",
       "rest_framework.authtoken",
       "fluent_comments",
       "threadedcomments",
       "django_comments",
       "wagtail.api.v2",
       "wagtail.contrib.forms",
       "wagtail.contrib.redirects",
       "wagtail.contrib.settings",
       "wagtail.embeds",
       "wagtail.sites",
       "wagtail.users",
       "wagtail.snippets",
       "wagtail.documents",
       "wagtail.images",
       "wagtail.search",
       "wagtail.admin",
       "wagtail.core",
       "wagtail_srcset",
       "modelcluster",
       "taggit",
    )

Add some middleware to your MIDDLEWARE_CLASSES setting:

.. code-block:: python

   MIDDLEWARE_CLASSES = (
       ...
       "django_htmx.middleware.HtmxMiddleware",
   )

Add some required configuration settings to your ``settings.py``:

.. code-block:: python

    COMMENTS_APP = "fluent_comments"


Modify your url-config to include the urls for django-cast and Wagtail:

.. code-block:: python

    from django.urls import path, include

    from wagtail import urls as wagtail_urls
    from wagtail.admin import urls as wagtailadmin_urls

    urlpatterns = [
        ...
        path("cast/", include("cast.urls", namespace="cast")),
        path("cms/", include(wagtailadmin_urls)),
        path("", include(wagtail_urls)),
    ]

Now run the following commands to create the database tables and a superuser:

.. code-block:: shell

    python manage.py migrate
    python manage.py createsuperuser

Run the development server and visit ``http://localhost:8000``:

.. code-block:: shell

    python manage.py runserver

To be able to extract posters from videos or get the duration of an audio
file you need to install `ffmpeg <https://ffmpeg.org/download.html>`_.
