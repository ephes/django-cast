=============================
Django Cast
=============================

.. image:: https://badge.fury.io/py/django-cast.svg
    :target: https://badge.fury.io/py/django-cast

.. image:: https://travis-ci.org/ephes/django-cast.svg?branch=master
    :target: https://travis-ci.org/ephes/django-cast

.. image:: https://codecov.io/gh/ephes/django-cast/branch/master/graph/badge.svg
    :target: https://codecov.io/gh/ephes/django-cast

Just another blogging / podcasting package

Documentation
-------------

The full documentation is at https://django-cast.readthedocs.io.

Quickstart
----------

Install Django Cast::

    pip install django-cast

Add django-cast and some dependencies to your ``INSTALLED_APPS``:

.. code-block:: python

    INSTALLED_APPS = (
        ...
        'imagekit',
        'ckeditor',
        'ckeditor_uploader',
        'rest_framework',
        'rest_framework.authtoken',
        'cast.apps.CastConfig',
        ...
    )



Add required settings:

.. code-block:: python

   # CKEditor
   CKEDITOR_UPLOAD_PATH = 'uploads/ckeditor/'
   CKEDITOR_IMAGE_BACKEND = 'pillow'
   AWS_QUERYSTRING_AUTH = False
   X_FRAME_OPTIONS = 'SAMEORIGIN'
   CKEDITOR_CONFIGS = {
   'default': {
    'removePlugins': 'stylesheetparser',
    'allowedContent': True,
    'enterMode': 2,
   },
   }

   # REST
   REST_FRAMEWORK = {
    # Use Django's standard django.contrib.auth permissions,
    # or allow read-only access for unauthenticated users.
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.TokenAuthentication',
    )
   }

   # django imagekit
   IMAGEKIT_DEFAULT_CACHEFILE_STRATEGY='imagekit.cachefiles.strategies.Optimistic'

Add Django Cast's URL patterns:

.. code-block:: python

    from django.urls import path

    from rest_framework.documentation import include_docs_urls
    from rest_framework.authtoken import views as authtokenviews


    urlpatterns = [
        ...
        path('cast/', include('cast.urls', namespace='cast')),
        path('api/api-token-auth/', authtokenviews.obtain_auth_token),
        path('docs/', include_docs_urls(title='API service')),
        path("ckeditor/", include('ckeditor_uploader.urls')),
        ...
    ]

The api token auth urls and the docs urls are both necessary to provide api endpoints
with the right namespace.

Features
--------

* TODO

Running Tests
-------------

Does the code actually work?

::

    source <YOURVIRTUALENV>/bin/activate
    (myenv) $ pip install tox
    (myenv) $ tox

Credits
-------

Tools used in rendering this package:

*  Cookiecutter_
*  `cookiecutter-djangopackage`_

.. _Cookiecutter: https://github.com/audreyr/cookiecutter
.. _`cookiecutter-djangopackage`: https://github.com/pydanny/cookiecutter-djangopackage
