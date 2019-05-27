Content
*******

The content of a blog post is just a normal django template. There are some special
templatetags and context variables, though.

Templatetags
============

There are some templatetags to include media models from uploads into your post content.
If you use the javascript editing frontend the primary keys for media models will be set
automatically.

Image
-----

To include an image, simply use the image templatetag:

.. code-block:: html

    {% image 1 %}

The number denotes the primary key of the image model. The templatetag will handle
the srset attribute for you automatically.

Gallery
-------

If you have more than one image you want to display, there's the gallery templatetag:

.. code-block:: html

    {% gallery 1 %}

The number denotes the primary key of the gallery model you want to include. The tag
will build a modal bootstrap dialog to show the included images as well as setting the
srcset attributes for the modally displayed images and the thumbnails.

Video
-----

To include an video, simply use the video templatetag:

.. code-block:: html

    {% video 1 %}

The number denotes the primary key of the video model. The templatetag will handle
the poster attribute for you automatically.

Audio
-----

To include an audio model, simply use the audio templatetag:

.. code-block:: html

    {% audio 1 %}

The number denotes the primary key of the audio model. The templatetag won't do that
much, because the player is pure javascript and chaptermarks and other metadata are pulled
from a rest-api by the player_. Note that you have to explicitly set the podcast_audio
if you want some audio model included as the podcast episode audio. There can only be
one such model whereas you can link to an arbitrary number of audio models that are
not the podcast episode audio.

Content in post list and detail view
====================================

If you want some content only to be visible on the post detail page, just wrap it with
an if-tag that evaluates a contenxt varible set by the list/detail view:

.. code-block:: html

    {% if include_detail %}
        This content will only be visible on the post detail page.
    {% endif  %}

This might be useful for long shownotes-sections you have sometimes for podcast episodes etc..

.. _`player`: https://podlove.org/podlove-web-player/
