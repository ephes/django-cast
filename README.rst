###########
Django Cast
###########

.. image:: https://badge.fury.io/py/django-cast.svg
    :target: https://badge.fury.io/py/django-cast

.. image:: https://travis-ci.org/ephes/django-cast.svg?branch=master
    :target: https://travis-ci.org/ephes/django-cast

.. image:: https://codecov.io/gh/ephes/django-cast/branch/master/graph/badge.svg
    :target: https://codecov.io/gh/ephes/django-cast

.. image:: https://img.shields.io/badge/code%20style-black-000000.svg
    :target: https://github.com/ephes/django-cast


Just another blogging / podcasting package

Documentation
*************

The full documentation is at https://django-cast.readthedocs.io.

Installation Screencast
***********************
.. raw:: html

    <div style="position: relative; padding-bottom: 56.25%; height: 0; overflow: hidden; max-width: 100%; height: auto;">
            <iframe src="https://www.youtube.com/embed/wPAYfpqg2EQ" frameborder="0" allowfullscreen style="position: absolute; top: 0; left: 0; width: 100%; height: 100%;"></iframe>
    </div>

Quickstart
**********

Install Django Cast::

    pip install django-cast

Add django-cast and some dependencies to your ``INSTALLED_APPS``:

.. code-block:: python

    INSTALLED_APPS = (
        ...
        "django.contrib.sites",
        "crispy_forms",
        "django_filters",
        "rest_framework",
        "rest_framework.authtoken",
        "cast.apps.CastConfig",
        "watson",
        "fluent_comments",
        "threadedcomments",
        "django_comments",
        ...
    )

    SITE_ID = 1

Add required settings:

.. code-block:: python

    # REST
    REST_FRAMEWORK = {
        # Use Django's standard django.contrib.auth permissions,
        # or allow read-only access for unauthenticated users.
        "DEFAULT_AUTHENTICATION_CLASSES": (
            "rest_framework.authentication.SessionAuthentication",
            "rest_framework.authentication.TokenAuthentication",
        )
    }

    # django imagekit
    IMAGEKIT_DEFAULT_CACHEFILE_STRATEGY="imagekit.cachefiles.strategies.Optimistic"

    # Comments
    COMMENTS_APP = 'fluent_comments'
    FLUENT_COMMENTS_EXCLUDE_FIELDS = ('email', 'url', "title")
    CAST_COMMENTS_ENABLED = True


Add Django Cast's URL patterns:

.. code-block:: python

    from django.urls import include, path, re_path

    from rest_framework.documentation import include_docs_urls
    from rest_framework.authtoken import views as authtokenviews


    urlpatterns = [
        ...
        # Cast urls
        path("api/api-token-auth/", authtokenviews.obtain_auth_token),
        path("docs/", include_docs_urls(title="API service")),
        # Cast
        path("cast/", include("cast.urls", namespace="cast")),
        # Threadedcomments
        re_path(r'^cast/comments/', include('fluent_comments.urls')),
        ...
    ]


The api token auth urls and the docs urls are both necessary to provide api endpoints
with the right namespace.

Features Overview
*****************

* Support for responsive images / video / audio media objects
* Use django template syntax for posts allowing you to use custom template tags for galleries etc. for example
* Chaptermarks for podcast Episodes
* Fulltext search via django-watson_
* Faceted navigation via django-filter_
* Comments for posts via django-contrib-comments_, django-threadedcomments_ and django-fluent-comments_


Running Tests
*************

Install Dependencies
--------------------

Non python packages that are required but need to be installed using your
operating system package manager:

* ffmpeg

Install packages that are required to be able to run the tests via poetry:

.. code-block:: shell

    $ poetry install

Run Tests
---------

Does the code actually work?

.. code-block:: shell

    $ poetry shell
    $ python runtests.py tests

Credits
*******

Tools used in rendering this package:

* django-imagekit_
* django-filter_
* django-watson_
* django-contrib-comments_
* django-threadedcomments_
* django-fluent-comments_
* podlove-web-player_
* podlove-subscribe-button_
* djangorestframework_
* django-model-utils_
* django-crispy-forms_
* Cookiecutter_
* `cookiecutter-djangopackage`_
* jquery_
* bootstrap_

.. _Cookiecutter: https://github.com/audreyr/cookiecutter
.. _`cookiecutter-djangopackage`: https://github.com/pydanny/cookiecutter-djangopackage
.. _`django-watson`: https://github.com/etianen/django-watson
.. _`django-filter`: https://github.com/carltongibson/django-filter
.. _`django-contrib-comments`: https://github.com/django/django-contrib-comments
.. _`django-threadedcomments`: https://github.com/HonzaKral/django-threadedcomments
.. _`django-fluent-comments`: https://github.com/django-fluent/django-fluent-comments
.. _`django-model-utils`: https://github.com/jazzband/django-model-utils
.. _`django-crispy-forms`: https://github.com/django-crispy-forms/django-crispy-forms
.. _`django-imagekit`: https://github.com/matthewwithanm/django-imagekit
.. _`djangorestframework`: https://www.django-rest-framework.org
.. _`podlove-web-player`: https://podlove.org/podlove-web-player/
.. _`podlove-subscribe-button`: https://podlove.org/podlove-subscribe-button/
.. _`jquery`: https://jquery.com
.. _`bootstrap`: https://getbootstrap.com/docs/4.0/getting-started/introduction/
