.. _transcript_overview:

***********
Transcripts
***********

You can upload transcript files to the server and display them
alongside the audio player. They will be also included in the feed
and can be used by podcast clients to display the transcript while
listening to the episode.

Transcript Models
=================

Transcript files are represented by the `Transcript` model. Transcripts have an
audio file they belong to, a `podlove` field that contains the transcript in
the form that the `Podlove Web Player <https://podlove.org/podlove-web-player/>`_
can use. And two other file formats that are used for to be referenced in the
feed:

* `vtt` - WebVTT, a subtitle format in plain text
* `dote` - DOTE, a json transcript format
