.. _images_and_galleries:

********************
Images and Galleries
********************

Django Cast provides comprehensive image handling with automatic responsive image generation, gallery support, and optimized delivery across all devices.

.. _image_overview:

Images
======

Images are mostly just the normal Wagtail Images. But they are
rendered using a ``picture`` tag supporting ``srcset`` and ``sizes`` attributes
for :ref:`responsive images <response_images_overview>`.

.. _response_images_overview:

Responsive Images
=================

Responsive images adapt to different screen sizes, ensuring optimal
display across devices. This project uses two types of responsive images:

- **Normal Images:** Displayed within page content.
- **Thumbnail Images:** Shown as thumbnails in content and enlarged in a modal upon clicking.

**Image Renditions:**
For each image, up to three renditions are created in each configured format
(AVIF and JPEG by default):

- **1x Width:** Standard size, used in the ``src`` attribute of the ``img`` tag.
- **2x Width:** Double size, included only when the original is large enough.
- **3x Width:** Triple size, included only when necessary.

These renditions are specified in the ``srcset`` attribute of the related ``source`` or ``img``
elements.

Normal Images
-------------

Normal images fill a slot with a width of 1110px and a maximum height of 740px.
But you can configure those values in the :ref:`settings <image_slot_dimensions>`.

Therefore, if you have an image which is quadratic and has a width of 3000px it
will rendered with a maximum width of 740px, but delivered with a width of 2220px
to high pixel density devices.

Both AVIF and JPEG formats are supported.

Thumbnail Images
----------------

Thumbnail images have a width of 120px and a maximum height of 80px. But you can
also set those values in the :ref:`settings <image_slot_dimensions>`.

They also support AVIF and JPEG formats.

.. _gallery_overview:

Galleries
=========

Galleries are a collection of images. They are used to display a
list of thumbnails and a larger view of the selected image. See
:ref:`responsive images <response_images_overview>` for more
information about thumbnails.

.. _gallery_model:

Gallery Model
-------------

The ``Gallery`` model is a simple container linking to multiple Wagtail
images via a many-to-many relationship. It inherits from
``TimeStampedModel``, providing ``created`` and ``modified`` timestamps.

Fields:

* ``images`` -- Many-to-many relationship to Wagtail ``Image`` objects.

Key properties and methods:

* ``image_ids`` -- Returns the set of primary keys for all images in the
  gallery.
* ``create_renditions()`` -- Creates any missing responsive renditions for
  every image in the gallery.

.. _gallery_creation:

Creating Galleries
------------------

Galleries are created automatically when images are selected in the
StreamField editor. The ``get_or_create_gallery()`` function handles this:

1. It receives a list of image IDs from the editor.
2. It looks up existing galleries whose image set matches exactly.
3. If a matching gallery already exists, it is reused.
4. If no match is found, a new ``Gallery`` is created and the images are
   associated with it.

This deduplication ensures that the same combination of images always
references the same gallery object. If none of the provided IDs resolve
to existing images, the function returns ``None``.

.. code-block:: python

    from cast.models.gallery import get_or_create_gallery

    # Returns an existing gallery, creates a new one, or returns None
    gallery = get_or_create_gallery([image1.pk, image2.pk, image3.pk])

.. _gallery_streamfield:

Galleries in StreamField
------------------------

Galleries are added to posts via the ``GalleryBlockWithLayout`` block,
which wraps a list of image choosers with an optional layout selector:

* **Web Component with Modal** (default) -- Renders thumbnails using the
  ``<image-gallery-bs4>`` web component with a modal for the full-size
  view.
* **HTMX based layout** -- Uses HTMX-powered server-side rendering for
  the gallery modal navigation.

.. code-block:: python

    from cast.blocks import GalleryBlockWithLayout

    body = StreamField([
        # ...
        ("gallery", GalleryBlockWithLayout()),
        # ...
    ])

.. _rendition_system:

Rendition System Internals
==========================

This section describes the rendition pipeline in ``cast/renditions.py``.
It is primarily useful for **theme developers** who need to understand how
images are sized and delivered in templates.

.. _rendition_core_types:

Core Types
----------

``Rectangle``
    A dataclass holding ``width`` (``Width``) and ``height`` (``Height``).
    Represents both image dimensions and slot dimensions. It is hashable
    so it can be used as a dictionary key.

``ImageType``
    A literal type with two values: ``"regular"`` and ``"gallery"``.
    Determines which set of slot dimensions is used (configured via
    ``CAST_REGULAR_IMAGE_SLOT_DIMENSIONS`` and
    ``CAST_GALLERY_IMAGE_SLOT_DIMENSIONS``).

``ImageFormat``
    A literal type for supported output formats: ``"jpeg"``, ``"avif"``,
    ``"webp"``, ``"png"``, ``"svg"``.

.. _rendition_filters_class:

RenditionFilters
----------------

``RenditionFilters`` is the central class that computes which Wagtail
renditions are needed for a given image. It is initialised with:

* ``image`` -- A ``Rectangle`` representing the original image dimensions.
* ``original_format`` -- The format of the original image file.
* ``slots`` -- A list of ``Rectangle`` objects representing the display
  slots the image must fit into.
* ``image_formats`` -- The output formats to generate (e.g.
  ``["jpeg", "avif"]``).

The class computes a *fitting width* for each slot by comparing the
image's aspect ratio with the slot's aspect ratio, then generates
``RenditionFilter`` objects for each slot/format/pixel-density combination
(1x, 2x, 3x). Renditions that would be nearly as large as the original
are skipped.

Convenience constructors:

* ``RenditionFilters.from_wagtail_image(image, slots, image_formats)`` --
  Creates filters from a Wagtail ``Image`` instance.
* ``RenditionFilters.from_wagtail_image_with_type(image, image_type)`` --
  Creates filters using the configured slot dimensions for the given
  ``ImageType``.

Key properties:

* ``filter_strings`` -- Returns a list of Wagtail filter spec strings
  (e.g. ``"width-300"``, ``"width-600|format-avif"``).
* ``all_filters`` -- Returns a flat list of all ``RenditionFilter`` objects.

.. _image_for_slot:

ImageForSlot
------------

``ImageForSlot`` represents a single image sized to fit a particular slot.
It carries the data needed to render a ``<picture>`` or ``<img>`` tag in a
template:

* ``width`` / ``height`` -- The display dimensions.
* ``sizes`` -- A CSS sizes string (e.g. ``"740px"``).
* ``src`` -- A dict mapping each ``ImageFormat`` to its URL (used for the
  ``src`` attribute).
* ``srcset`` -- A dict mapping each ``ImageFormat`` to a srcset string
  (e.g. ``"image.avif 300w, image.avif 600w"``).

In templates, each image gets ``regular``, ``thumbnail``, or ``modal``
attributes (depending on context) that are ``ImageForSlot`` instances.
Theme templates can access ``image.regular.srcset``,
``image.regular.src``, etc. to build responsive ``<picture>`` elements.

.. _rendition_workflow:

Rendition Workflow
------------------

The full rendering pipeline works as follows:

1. When a post is requested, the repository pattern prefetches all images
   and their existing renditions in bulk.
2. Each image block (``CastImageChooserBlock`` or ``GalleryBlockWithLayout``)
   creates a ``RenditionFilters`` instance for the image.
3. The filter strings are matched against prefetched renditions. In the
   normal path all required renditions are already present. If a rendition
   is missing (e.g. the image was not in the repository), Wagtail's
   ``image.get_rendition()`` is called as a fallback.
4. The ``get_image_for_slot()`` method produces an ``ImageForSlot`` object
   that is attached to the image and passed to the template context.
5. Theme templates use the ``ImageForSlot`` attributes to render
   ``<picture>`` elements with appropriate ``<source>`` and ``<img>`` tags.

To create missing renditions in bulk (e.g. after changing slot
dimensions), use the management command::

    python manage.py sync_renditions
