.. _podcasts_and_episodes:

*********************
Podcasts and Episodes
*********************

Django Cast provides comprehensive podcast support built on top of its blogging functionality. This section covers both podcast configuration and episode management.

.. _podcast_overview:

Podcasts
========

Podcasts are :ref:`blogs <blog_overview>` that have some additional features to
better support podcasting.

There are some additional fields that are available for podcasts:

Itunes Artwork
--------------
The image that will be used in the podcast feed as the iTunes artwork.

.. _episode_overview:

Episodes
========

Podcast episodes are Wagtail pages that have a :ref:`podcast <podcast_overview>`
page as a parent. They have the same features as blog :ref:`posts <post_overview>`,
but with some additional fields for better podcast support.

Cover Image
-----------

In addition to the effect setting a cover image for a post has, setting a
cover image for an episode will also be used as the episode's artwork in the
podcast feed and in the Podlove Web Player.
It is also used for social previews via the automatically generated 1200x630
social rendition.

If no cover image is set for the episode, the :ref:`blog <blog_overview>`'s cover
image will be used.

Podcast Audio
-------------

The `podcast_audio` field is required for an episode. It is used for the
enclosure tag in the podcast feed.

Promote > Title
---------------

This will be used as the title of the episode in the Podlove Web Player.

Promote > Description
---------------------

This will be used as the description of the episode in the Podlove Web Player.

Keywords
--------

Keywords are set in the podcast feed as the iTunes keywords tag.

Explicit
--------

Explicit content is set in the podcast feed as the iTunes explicit tag. The available options are:

- **Yes**: Content is suitable for the age group it's rated for
- **No**: Content does not contain anything explicit and is safe for general audiences
- **Explicit**: Contains adult content or strong language, not recommended for younger audiences

Block
-----

Indicates whether the episode is blocked from iTunes or not.
