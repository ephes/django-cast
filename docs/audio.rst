*****
Audio
*****

You can upload audio files to the server and play them back in the browser.

Audio Models
============

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
========

For playback of audio content `Podlove Web Player <https://podlove.org/podlove-web-player/>`_
version 4 is used.

.. Hint::

    Currently supported features:

    * Chapter marks
    * Download button
