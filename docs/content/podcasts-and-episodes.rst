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

Automatic Episode Numbering
---------------------------

Automatic episode numbering is disabled by default for every podcast. To enable
it, edit the podcast page in Wagtail and turn on **Automatic episode numbering**
in the podcast settings panel. The **Next episode number** field controls the
next podcast-scoped number django-cast will try to assign.

When enabled, django-cast assigns a number only when a blank full episode is
first really published. Saving a draft does not consume a number, and scheduling
a future publish does not consume a number until Wagtail actually publishes the
episode. Blank episode type is treated as full for this policy. Trailer and
bonus episodes do not consume numbers in this first implementation.

Editors can still set episode numbers manually. Automatic assignment never
rewrites a non-empty episode number, and it skips numbers that are already used
by another episode under the same podcast. This can leave gaps in the sequence;
avoiding duplicate public numbers is more important than strict contiguity.
Episode numbers remain publishing metadata only. RSS GUIDs, slugs, and URLs are
not derived from episode numbers.

.. _episode_overview:

Episodes
========

Podcast episodes are Wagtail pages that have a :ref:`podcast <podcast_overview>`
page as a parent. They have the same features as blog :ref:`posts <post_overview>`,
but with some additional fields for better podcast support.

Cover Image
-----------

In addition to the effect setting a cover image for a post has, setting a
cover image for an episode will also be used in the Podlove Web Player.
Podlove posters use an automatically generated max-512x512 WebP rendition to
keep image sizes reasonable.
It is also used for social previews via the automatically generated 1200x630
social rendition.

If no cover image is set for the episode, the :ref:`blog <blog_overview>`'s cover
image will be used.

Podcast Audio
-------------

The `podcast_audio` field may be empty while an episode is a draft, but the
built-in Wagtail form requires it when publishing. It supplies the enclosure
for the episode in the podcast feed.

Promote > Title
---------------

This will be used as the title of the episode in the Podlove Web Player.

Promote > Description
---------------------

This will be used as the description of the episode in the Podlove Web Player.

Keywords
--------

Keywords are set in the podcast feed as the iTunes keywords tag.

Podcast Type
------------

Podcast pages can optionally set an Apple Podcasts channel type:
``episodic`` or ``serial``. Leaving the field blank omits ``itunes:type`` and
preserves the existing feed behavior. Set it explicitly only when the show has a
known ordering policy for podcast directories.

Podcast Publishing Metadata
---------------------------

Episodes can carry optional podcast publishing metadata:

- ``episode_number``: a positive episode number for iTunes and Podcasting 2.0
  feed metadata.
- ``episode_type``: one of ``full``, ``trailer``, or ``bonus``. Leaving it blank
  omits the feed tag and is equivalent to ``full``.
- ``season``: a reusable podcast-scoped season with a positive season number
  and optional name.

Podcast clients identify feed items by GUID. Episode numbers, types, and
seasons are metadata for podcast directories and apps; changing them does not
change feed identity.

Contributors
------------

Episode contributors are reusable Wagtail snippets for people who should be
credited on podcast episodes and in Podcasting 2.0 feed metadata.

Create contributors in Wagtail under **Contributors**. They remain available as
snippets under **Snippets > Contributors** as well. A contributor has a display
name, a stable slug, a default episode role, an optional avatar, an optional
short bio, and ordered profile links. Profile links use fixed service choices
such as Website, GitHub, Mastodon, Twitter/X, LinkedIn, and YouTube. The first
ordered profile link is used as the default episode link.

Contributors have a global ``visible`` flag. Turning it off hides that person
from public episode pages and podcast feeds without deleting existing episode
assignments.

On an episode edit page, use the **Contributors** panel to add ordered
contributors. Each assignment chooses a contributor, a role of **Host** or
**Guest**, and optionally one of the contributor's links to use for that episode.
After a contributor is selected, the link field only offers that contributor's
profile links. New assignments use the contributor's default role and first
ordered profile link, but editors can still change both fields per episode.
The same contributor may appear on an episode under more than one role (for
example as both **Host** and **Guest**), but a given (contributor, role) pair
can only be assigned once per episode. Episode assignments may reference one of
the contributor's existing links; links that are in use cannot be deleted or
moved to another contributor until those assignments are updated.

Public episode templates receive ``episode_contributors`` in context. The
built-in themes render those assignments on episode detail pages. Custom themes
that override episode body templates should render ``episode_contributors`` or
include ``cast/contributors.html`` to show episode credits. Use this filtered
context value instead of iterating ``episode.contributor_assignments`` directly;
it omits contributors whose global ``visible`` flag is disabled. Contributor
avatars are served as ``fill-80x80|format-webp`` renditions so the original
upload is not used as a thumbnail.

Podcast feed items emit one ``podcast:person`` element for each visible
assignment. The element text is the contributor display name, ``role`` is the
episode assignment role, ``img`` is the contributor avatar rendition URL when
configured, and ``href`` is the selected assignment link when configured.

Explicit
--------

Explicit content is set in the podcast feed as the iTunes explicit tag. The available options are:

- **Yes**: Mark the episode as explicit
- **No**: Mark the episode as not explicit
- **Clean**: Mark an edited or censored version as clean

Block
-----

Indicates whether the episode is blocked from iTunes or not.
