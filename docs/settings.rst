########
Settings
########

Documentation of all the configuration variables you can add to your
``DJANGO_SETTINGS_MODULE`` file.

********
Comments
********

.. _cast_comments_enabled:

CAST_COMMENTS_ENABLED
=====================

Whether or not to enable comments on the site. Defaults to ``False``.

**********
Pagination
**********

POST_LIST_PAGINATION
====================

The number of posts to show per page on the user facing blog list page.
Defaults to ``5``.

CHOOSER_PAGINATION
==================

The number of items (audio, video or image) to show per page in the wagtail
admin chooser. Defaults to ``10``.

MENU_ITEM_PAGINATION
====================

The number of items (audio, video, or image) to show per page in the
wagtail admin menu. Defaults to ``20``.

******
Images
******

DELETE_WAGTAIL_IMAGES
=====================

Whether or not to delete the original image when a Wagtail image
model is removed. Defaults to ``True``. This is useful if you are
using an object store like S3 to store your images and want to avoid
having your production images deleted when you try out stuff in your
development environment.

*********
Templates
*********

Custom Theme Configuration
==========================

To configure custom themes for the site, use the ``CAST_CUSTOM_THEMES`` setting.
By default, it is set to an empty list ``[]``. Each theme requires two elements:
a name and a display. For instance:

.. code-block:: python

    CAST_CUSTOM_THEMES = [
        # (name, display)
        ("my_theme", "My Theme"),
        ("my_other_theme", "My Other Theme"),
    ]

The display value is the title displayed in the theme selector within the Wagtail
admin panel. The name corresponds to the theme's base directory inside your templates
folder. To create a theme named my_theme, make a directory called ``cast/my_theme``
within your templates folder and place your templates inside.
