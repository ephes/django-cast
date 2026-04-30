.. _audio_and_transcripts:

*********************
Audio and Transcripts
*********************

Django Cast provides comprehensive audio support for podcasting, including multiple format handling, chapter marks, and transcript integration with the Podlove Web Player.

.. _audio_overview:

Audio
=====

You can upload audio files to the server and play them back in the browser.

Audio Models
------------

Audio files are represented by the `Audio` model. Audio files have a `title`, a
`subtitle`, `tags` and four file fields pointing to the file in different audio formats:

* `m4a` - AAC, works best on Apple/iOS devices
* `mp3` - MP3, works everywhere, but has no time index so the whole file has to be downloaded before playback can start
* `oga` - OGG Vorbis, maybe remove this one because apple is now adding support for opus, too
* `opus` - Opus, better quality per bitrate than all other formats, but not as well known as the others

Since podcast feeds only support one audio file per episode, there is one feed
per audio format. The feeds are generated automatically and can be found at
`feed/podcast/<audio_format>/rss.xml`.

Playback
--------

For playback of audio content `Podlove Web Player <https://podlove.org/podlove-web-player/>`_
version 5 is used.

.. Hint::

    Currently supported features:

    * Chapter marks
    * Download button

.. note::

    The Bootstrap templates defer Podlove player initialization on list pages by
    setting ``data-load-mode="click"`` on the player element. Remove the
    attribute in your templates to keep automatic initialization behavior.

.. note::

    The Podlove Web Player theme is configured via
    ``/api/audios/player_config/``. You can override the default tokens and
    fonts per theme using the ``CAST_PODLOVE_PLAYER_THEMES`` setting.

.. _transcript_overview:

Transcripts
===========

You can upload transcript files to the server and display them
alongside the audio player. They will be also included in the feed
and can be used by podcast clients to display the transcript while
listening to the episode.

Transcript Models
-----------------

Transcript files are represented by the `Transcript` model. Transcripts have an
audio file they belong to, a `podlove` field that contains the transcript in
the form that the `Podlove Web Player <https://podlove.org/podlove-web-player/>`_
can use. And two other file formats that are used for to be referenced in the
feed:

* `vtt` - WebVTT, a subtitle format in plain text
* `dote` - DOTE, a json transcript format

Voxhelm Integration
-------------------

If your audio files are available through absolute HTTP(S) URLs, you can use
the Wagtail admin or the built-in ``generate_transcripts`` management command
to request a transcription from Voxhelm and populate all three transcript
artifacts on the existing ``Transcript`` model.

In Wagtail admin, editors with the required page/media permissions can trigger
transcript generation directly from:

* an episode edit view
* an audio edit view

The admin request now returns after the Voxhelm batch job has been submitted
and a local completion task has been queued. Editors see local
queued/running/succeeded/failed status on the same Episode and Audio edit
surfaces while the background worker polls Voxhelm, downloads the artifacts,
and updates the ``Transcript`` model.

Site admins can manage the Voxhelm API base URL, API token, and optional
model/language defaults in ``Settings -> Voxhelm settings``.

To make the non-blocking Wagtail flow work, configure Django Tasks with the
database backend and run a worker alongside Django. Keep the global
``default`` backend immediate so third-party apps that decorate tasks at
import time do not pull in the database backend before app loading has
finished:

.. code-block:: python

    INSTALLED_APPS += ["django_tasks", "django_tasks_db"]

    TASKS = {
        "default": {
            "BACKEND": "django_tasks.backends.immediate.ImmediateBackend",
        },
        "cast_transcripts": {
            "BACKEND": "django_tasks_db.DatabaseBackend",
        },
    }

.. code-block:: bash

    python manage.py db_worker --backend cast_transcripts --worker-id cast-transcripts

Use a stable, distinct ``--worker-id`` for each deployed site. See
:doc:`../operations/deployment` for deployment examples.

.. code-block:: bash

    # Operator fallback
    python manage.py generate_transcripts --episode-id 42

django-cast now consumes Voxhelm-owned Podlove, DOTe, and WebVTT transcript
artifacts directly from the batch job result and persists them onto the
existing ``Transcript`` model without local format conversion.
