=====
Usage
=====

To use Django Cast in a project, add it to your `INSTALLED_APPS`:

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
