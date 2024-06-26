*******
Episode
*******

Podcast episodes are Wagtail pages that have a :ref:`podcast <podcast_overview>`
page as a parent. They have the same features as blog :ref:`posts <post_overview>`,
but with some additional fields for better podcast support.

Cover Image
===========

In addition to the effect setting a cover image for a post has, setting a
cover image for an episode will also be used as the episode's artwork in the
podcast feed and in the Podlove Web Player.

If no cover image is set for the episode, the :ref:`blog <blog_overview>`’s cover
image will be used.

Podcast Audio
=============

The `podcast_audio` field is required for an episode. It is used for the
enclosure tag in the podcast feed.

Promote > Title
===============

This will be used as the title of the episode in the Podlove Web Player.

Promote > Description
=====================

This will be used as the description of the episode in the Podlove Web Player.

Keywords
========

Keywords are set in the podcast feed as the iTunes keywords tag.

Explicit
========

Explicit content is set in the podcast feed as the iTunes explicit tag.

Block
=====

Indicates whether the episode is blocked from iTunes or not.
