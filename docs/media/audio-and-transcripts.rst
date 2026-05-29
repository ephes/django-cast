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

When an existing API token is stored in Wagtail, the token field is intentionally
blank when you reopen the settings form. If the help text says that a token is
configured, submit the form with the field blank to keep the stored token, or
enter a new token to replace it.

Production sites can also keep Voxhelm credentials in deployment-managed Django
settings or environment variables instead of the Wagtail database. django-cast
looks up site-level Wagtail values first, then Django settings, then environment
variables. Use ``CAST_VOXHELM_API_BASE`` and ``CAST_VOXHELM_API_KEY`` for the
required service URL and bearer token; optional defaults use
``CAST_VOXHELM_MODEL``, ``CAST_VOXHELM_LANGUAGE``, and
``CAST_VOXHELM_DIARIZATION_ENABLED``. If the token should be managed as a
deployment secret, leave the Wagtail API token blank and provide
``CAST_VOXHELM_API_KEY`` to both the web process and transcript worker.

Each audio object also has a transcript diarization mode. The default
``inherit`` mode keeps using the site/global Voxhelm diarization setting for
future transcript generation. Editors can set an individual audio to
``enabled`` to request diarization even when the site/global default is off, or
to ``disabled`` to submit future Voxhelm jobs without the diarization payload or
speaker-count hint. The setting belongs to the shared audio transcript, so
changing it can affect every episode that uses the same audio.

Disabling diarization is non-destructive. It keeps transcript text, timestamps,
and stored Podlove, DOTe, and WebVTT files in place, but public transcript
surfaces hide stored speaker labels for that audio. Re-enable the mode later to
allow existing labels to appear again when they pass the live-contributor
sanitizer.

To make the non-blocking Wagtail flow work, install the optional
``transcript-worker`` extra, configure Django Tasks with the database backend,
and run a worker alongside Django. The extra requires a Wagtail/django-tasks
combination compatible with ``django-tasks-db`` 0.12; Wagtail 7.0 LTS uses
``django-tasks`` 0.7 and is not compatible with that database backend. Keep the
global ``default`` backend immediate so third-party apps that decorate tasks at
import time do not pull in the database backend before app loading has finished:

.. code-block:: bash

    uv pip install "django-cast[transcript-worker]"

.. code-block:: python

    INSTALLED_APPS += ["django_tasks_db"]

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

When generated transcripts include diarization speaker labels, the Wagtail
transcript edit form lets editors map those labels to episode contributors.
The mapping form shows short transcript samples for each speaker and, when the
audio file is playable from the admin, timestamp controls that seek the audio
preview to the sample position. Applying a mapping rewrites the stored Podlove
and DOTe speaker fields and matching WebVTT voice labels.

Generated transcript text is stored with the shared audio file and can appear
on already published episodes as soon as generation completes. Public speaker
metadata is stricter: player JSON, public transcript JSON, PodcastIndex JSON,
HTML transcript pages, and supported WebVTT speaker labels only expose speaker
names that match visible contributors on the live episode. Draft-only
contributor mappings and unmapped diarization labels such as ``Speaker 1`` are
hidden from public output until the matching contributor assignment is
published. If a transcript is not connected to any live episode yet, public
transcript endpoints expose no speaker labels. The stored transcript files are
not rewritten by this public sanitization step.

Private contributor voice references
------------------------------------

Anonymous diarization clusters voices but cannot reliably identify a known
recurring speaker, and the speaker-mapping form can only rename clusters that
diarization actually produced. To support known-speaker recognition, a
contributor can carry private *voice references*: reviewed clean-solo speech
that a known-speaker backend can use to recognise that contributor's voice.

Voice references are sensitive, admin-only editorial data. They are **never**
exposed through public contributor APIs, podcast feeds, theme context,
repository serialization, static exports, or public transcript output. Manage
them from the Wagtail contributor snippet under *Voice references (private)*.

Each reference is either an uploaded clean-solo clip **or** a source range into
existing audio, never both:

- A *source range* points at an existing :class:`Audio` object with
  ``start_seconds`` and ``end_seconds`` (start must be before end).
- An *uploaded clip* is stored through a protected storage backend. Configure a
  non-public backend under the ``"cast_voice_references"`` alias in
  ``STORAGES`` so reference clips are not served from public media; when the
  alias is absent django-cast falls back to the default storage and you must
  protect it yourself.

References start as ``pending`` and must be explicitly ``approved`` before they
can be sent to a known-speaker backend. Approval requires confirming contributor
consent (``consent_confirmed``). The remaining statuses are ``disabled`` and
``rejected``, both retained for audit but never used. Hiding or disabling a
public contributor never deletes reference material; a hidden contributor is
also excluded from known-speaker use for public transcripts unless an editor
explicitly opts a reference in with ``allow_for_hidden_contributor``.

Voice references store only reviewed reference material and editorial state.
They deliberately do **not** store model-specific voice embeddings, because
embeddings are owned by the transcription backend and would become stale when
that backend changes its embedding model.
