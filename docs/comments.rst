Comments
********

You can enable / disable comments on app, blog and post-level. For app-level,
there's a global switch you can use in the settings. Blog and post models have
a comments_enabled database field. They are set to True by default.

Settings
========

.. code-block:: python

    # Switch to enable/disable comments globally. By default it's False
    CAST_COMMENTS_ENABLED = True

Caveats
=======

The ajax-calls django-fluent-comments_ does depend on the availability of a
full jquery_ version. The min-version shipped by cookiecutter-django_
is not sufficient, therefore an additional jquery_ version is loaded on the
post detail page when comments are enabled.

.. _`cookiecutter-django`: https://github.com/pydanny/cookiecutter-django
.. _`django-fluent-comments`: https://github.com/django-fluent/django-fluent-comments
.. _`jquery`: https://jquery.com
