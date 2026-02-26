.. _troubleshooting_overview:

***************
Troubleshooting
***************

This section covers common issues and their solutions.

Image Renditions
================

Missing or broken images
------------------------

If images appear broken or missing on the frontend:

1. Ensure renditions have been generated:

   .. code-block:: bash

       python manage.py sync_renditions

2. If you recently changed ``CAST_REGULAR_IMAGE_SLOT_DIMENSIONS`` or
   ``CAST_GALLERY_IMAGE_SLOT_DIMENSIONS``, run ``sync_renditions`` again.
   It will create missing renditions and delete obsolete ones.

3. For a specific post or blog:

   .. code-block:: bash

       python manage.py sync_renditions --post-slug my-post
       python manage.py sync_renditions --blog-slug my-blog

Stale Vite Assets
=================

If you see Django system check warning ``cast.W001``, your Vite-built
JavaScript assets are older than the JavaScript source files. Rebuild them:

.. code-block:: bash

    just js-build-vite
    # or to rebuild all JavaScript assets:
    just js-build-all

This regenerates the image gallery and Podlove audio player bundles.

Audio and Podcasts
==================

Missing audio duration
----------------------

Audio duration is computed automatically when an audio object is saved.
If duration is missing for older files, re-save the audio object in the
Wagtail or Django admin to trigger recomputation.

Chapter marks not appearing
---------------------------

Chapter marks can be entered manually or extracted automatically from
audio file metadata via ``ffprobe``. Ensure ``ffprobe`` (part of the
FFmpeg package) is installed on your system if you want automatic
extraction.

Video poster images also require ``ffmpeg``. See
:ref:`recalc_video_posters <cast_management_commands>` for regenerating
posters.

Media Storage
=============

Production images deleted from development
-------------------------------------------

If you share a storage backend (e.g., S3 bucket) between environments,
set in your development settings:

.. code-block:: python

    DELETE_WAGTAIL_IMAGES = False

This prevents Wagtail from deleting the original image file on S3 when
an image model is removed locally.

Finding unreferenced media files
--------------------------------

Over time, media files may accumulate that are no longer referenced by
any database record. To find them:

.. code-block:: bash

    python manage.py media_stale

To also delete them:

.. code-block:: bash

    python manage.py media_stale --delete

Themes and Templates
====================

Theme not applying
------------------

Theme resolution follows this precedence (highest wins):

1. Internal ``request.cast_template_base_dir`` override (used by styleguide)
2. ``?theme=`` or ``?template_base_dir=`` query parameter (temporary preview)
3. Django session value (persistent user choice via theme selector)
4. Blog-level ``template_base_dir`` field
5. Site-level ``TemplateBaseDirectory`` Wagtail setting

If a theme is not applying, check that the template directory exists at
``cast/<theme_name>/`` within one of your installed apps' template directories.
Also verify that a session or query-parameter override is not taking precedence.

Spam Filter
===========

Poor spam detection accuracy
-----------------------------

The built-in Naive Bayes spam filter improves with training data. To retrain
it from scratch using existing comment classifications:

1. Go to Django Admin > Spam Filters
2. Select your spam filter
3. Use the "Retrain model from scratch using marked comments" action

The filter's precision and recall metrics are shown in the admin list view.

Comments Not Appearing
======================

If comments are not visible on posts:

1. Verify ``CAST_COMMENTS_ENABLED = True`` in settings
2. Check that ``comments_enabled = True`` on the specific Blog page
3. Ensure the commenting app is in ``INSTALLED_APPS`` (included
   automatically via ``CAST_APPS``)

Video Poster Images
===================

If video poster images are missing or incorrect, regenerate them:

.. code-block:: bash

    python manage.py recalc_video_posters

This requires ``ffmpeg`` to be installed on your system.
