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
