.. _video_overview:

*****
Video
*****

Django Cast provides video file management with automatic poster frame
extraction, dimension detection, and integration with Wagtail's StreamField
editor.

.. _video_model:

Video Model
===========

Videos are represented by the ``Video`` model. Each video has the following
fields:

* ``user`` -- The user who uploaded the video (foreign key).
* ``title`` -- A short title for the video (up to 255 characters).
* ``original`` -- The uploaded video file (stored under ``cast_videos/``).
* ``poster`` -- An auto-generated or manually uploaded poster image
  (stored under ``cast_videos/poster/``). May be blank.
* ``poster_seconds`` -- The timestamp (in seconds) from which the poster
  frame is extracted. Defaults to ``1``.
* ``tags`` -- Tags for organising and searching videos.

The model also inherits Wagtail ``CollectionMember`` (so videos belong to
collections) and ``TimeStampedModel`` (providing ``created`` and ``modified``
timestamps).

.. _video_poster_generation:

Poster Generation
=================

Each time a video is saved, Django Cast checks whether a poster image
already exists. If not, it automatically extracts a single frame to use
as the poster.

Requirements
------------

Both **FFmpeg** and **FFprobe** must be installed and available on the
system ``PATH``:

.. code-block:: bash

    # Ubuntu / Debian
    sudo apt-get install ffmpeg

    # macOS
    brew install ffmpeg

How It Works
------------

1. On ``Video.save()``, the ``create_poster()`` method is called
   automatically.
2. If a poster already exists or the class attribute ``calc_poster`` is
   ``False``, the step is skipped.
3. ``FFprobe`` is used to detect the original video dimensions (width and
   height), including portrait orientation handling.
4. ``FFmpeg`` extracts a single frame at the timestamp given by
   ``poster_seconds`` (default 1 second) and writes it to a temporary JPEG
   file.
5. The temporary file is saved to the ``poster`` field and then cleaned up.

If FFmpeg or FFprobe is not installed (or the command fails for any other
reason), the error is logged and the video is saved without a poster.
Poster generation never raises an exception to the caller.

You can regenerate the poster for a video by clearing the existing poster
and calling ``create_poster()``:

.. code-block:: python

    video.poster = None
    video.poster_seconds = 5.0   # extract at 5 seconds instead
    video.create_poster()
    video.save(poster=False)     # save without re-triggering poster generation

To create posters for all videos that are currently missing one, use the
management command::

    python manage.py recalc_video_posters

.. note::

    This command only fills in **missing** posters. If a poster already
    exists it is kept. To force regeneration for a specific video, clear
    its poster first (``video.poster = None; video.save(poster=False)``)
    and then re-run the command or call ``video.create_poster()``.

.. _video_dimensions:

Dimension Detection
===================

Video dimensions are detected via ``FFprobe``. The parser understands
H.264, HEVC, and SAR-based dimension lines and automatically swaps width
and height for portrait videos (detected by rotation metadata or a 9:16
display aspect ratio).

.. _video_mime_type:

MIME Types
==========

The ``get_mime_type()`` method returns a MIME type based on the file
extension:

* ``.mp4`` -- ``video/mp4``
* ``.mov`` -- ``video/quicktime``
* ``.avi`` -- ``video/x-msvideo``

All other extensions default to ``video/mp4``.

.. _video_streamfield:

Using Videos in StreamField
===========================

Videos are added to posts via the ``VideoChooserBlock`` in Wagtail's
StreamField editor. The block uses a modal chooser that lets editors search
and select existing videos or upload new ones.

In the post model the block is declared as part of the body StreamField:

.. code-block:: python

    from cast.blocks import VideoChooserBlock

    body = StreamField([
        # ...
        ("video", VideoChooserBlock()),
        # ...
    ])

The ``VideoChooserBlock`` integrates with the repository pattern so that
video data is prefetched efficiently when rendering pages.
