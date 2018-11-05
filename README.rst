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

Add it to your `INSTALLED_APPS`:

.. code-block:: python

    INSTALLED_APPS = (
        ...
        'cast.apps.CastConfig',
        ...
    )

Add Django Cast's URL patterns:

.. code-block:: python

    from cast import urls as cast_urls


    urlpatterns = [
        ...
        url(r'^', include(cast_urls)),
        ...
    ]

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
