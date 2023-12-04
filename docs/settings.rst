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

CAST_IMAGE_FORMATS
==================
For which image formats to generate thumbnails / srcset / source renditions. Defaults to
``["jpeg", "avif"]``.

.. _image_slot_dimensions:

CAST_IMAGE_SLOT_DIMENSIONS
==========================

The dimensions of the image slots in blog posts and the modal shown
when clicking on thumbnail gallery images. Defaults to
``(1110, 740)``.

CAST_THUMBNAIL_SLOT_DIMENSIONS
===============================

The dimension of image slots for thumbnails in blog posts. Defaults
to ``(120, 80)``.

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
within your templates folder and place your templates inside. asdf

********
Storages
********

Configure Backup Storage
========================

If you store your media files on S3, you can configure a local backup storage
like this:

.. code-block:: python

    STORAGES = {
      "default": {"BACKEND": "config.settings.local.CustomS3Boto3Storage"},
      "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
      "production": {"BACKEND": "config.settings.local.CustomS3Boto3Storage"},
      "backup": {
          "BACKEND": "django.core.files.storage.FileSystemStorage",
          "OPTIONS": {
              "location": ROOT_DIR.path("backups").path("media"),
          },
      },
    }


.. important::

    This will only work if you are using Django >= 4.2.


******************
Faceted Navigation
******************

You can configure the facets that are available in the search UI by
setting the ``CAST_FILTERSET_FACETS`` variable in your settings file.
The default value is:

.. code-block:: python

    CAST_FILTERSET_FACETS = [
        "search", "date", "date_facets", "category_facets", "tag_facets"
    ]

But if you want to remove the ``tag_facets`` facet, because you don't
use tags, you can do it like this:

.. code-block:: python

    CAST_FILTERSET_FACETS = [
        "search", "date", "date_facets", "category_facets"
    ]
