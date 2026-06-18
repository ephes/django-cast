######
Models
######

Django Cast provides a comprehensive set of models for blogging, podcasting, and media management. The models are organized into several categories: page models, media models, content enhancement, and supporting infrastructure.

Some reference documentation about how the models work.

************
Page Models
************

Page models define the content structure and hierarchy using Wagtail's page tree system.

HomePage
========

The site's root page that can optionally redirect to another page.

.. code-block:: python

    class HomePage(Page):
        body = StreamField(...)  # Content blocks
        alias_for_page = ForeignKey(Page)  # Optional redirect

**Key Features:**

- Can redirect to any other page via ``alias_for_page``
- Supports basic content blocks (heading, paragraph, image, gallery)
- Serves as the site root in Wagtail's page tree

Blog
====

Container page for blog posts with author information and configuration.

.. code-block:: python

    class Blog(Page):
        author = CharField(max_length=255)
        email = EmailField()
        uuid = UUIDField()
        comments_enabled = BooleanField(default=True)
        cover_image = ForeignKey('wagtailimages.Image')
        cover_alt_text = CharField(max_length=255)
        noindex = BooleanField(default=False)
        template_base_dir = CharField(max_length=128)
        subtitle = CharField(max_length=255)
        description = RichTextField()

**Key Methods:**

- ``get_template_base_dir()``: Returns the theme directory for templates
- ``get_published_posts()``: Returns queryset of live child posts
- ``get_filterset()``: Returns filterset for faceted search
- ``get_pagination_context()``: Handles pagination of posts

**Properties:**

- ``last_build_date``: DateTime of most recent post
- ``unfiltered_published_posts``: All published posts without filtering

Podcast
=======

Specialized blog for podcasting with iTunes-specific metadata.

.. code-block:: python

    class Podcast(Blog):
        itunes_artwork = ForeignKey(ItunesArtWork)
        itunes_categories = CharField()  # JSON field
        keywords = CharField(max_length=255)
        explicit = PositiveSmallIntegerField(choices=EXPLICIT_CHOICES)

**Additional Features:**

- Inherits all Blog functionality
- Adds podcast-specific fields for feed generation
- ``itunes_categories_parsed`` property returns parsed categories

Season
======

Reusable podcast season metadata scoped to a single ``Podcast``.

.. code-block:: python

    class Season(models.Model):
        podcast = ForeignKey(Podcast, related_name="seasons")
        number = PositiveIntegerField()
        name = CharField(max_length=128, blank=True)

**Key Features:**

- Normal model scoped to one podcast and selectable from episode editing
- ``number`` must be a positive non-zero integer
- ``name`` is optional and capped at 128 characters for Podcasting 2.0 output
- ``(podcast, number)`` is unique, so one podcast cannot define the same season
  number twice
- Ordered by podcast and season number

Post
====

A post is a single blog post. It's the parent of episodes, too.

Main content model for blog posts with rich media support.

.. code-block:: python

    class Post(Page):
        uuid = UUIDField()
        visible_date = DateTimeField()
        comments_enabled = BooleanField()
        cover_image = ForeignKey('wagtailimages.Image')
        cover_alt_text = CharField(max_length=255)
        body = StreamField([
            ("overview", ContentBlock(section="overview")),
            ("detail", ContentBlock(section="detail")),
        ])

        # Media relationships
        images = ManyToManyField(Image)
        videos = ManyToManyField(Video)
        galleries = ManyToManyField(Gallery)
        audios = ManyToManyField(Audio)

        # Categorization
        categories = ParentalManyToManyField(PostCategory)
        tags = ClusterTaggableManager()

**StreamField Structure:**

The ``body`` field contains two sections:

- ``overview``: Summary content shown on index pages
- ``detail``: Full content shown on detail pages

Both sections support django-cast's built-in blocks for text, images,
galleries, video, audio, code, and embeds. Projects can append custom blocks per
section with ``CAST_POST_BODY_BLOCKS``; those custom blocks are inherited by
episodes because episodes use ``Post.body``.

**Key Methods:**

- ``sync_media_ids()``: Syncs media from StreamField to relationships
- ``get_all_images()``: Returns all images including from galleries
- ``get_description()``: Renders content for feeds and meta tags
- ``get_repository()``: Returns optimized data repository

**Properties:**

- ``blog``: Parent Blog instance
- ``has_audio``: Boolean indicating audio presence
- ``comments_are_enabled``: Checks if comments allowed
- ``media_lookup``: Dict mapping media types to objects
- ``podlove_players``: Configuration for audio players

Template Logic
--------------

Since you can set a base directory for templates, the `get_template`
method is overridden to get the base directory from the request and
return the correct template.

To be able to render the description of a post without the base template,
there's a `_local_template_name` attribute set on the `Post` class that
can be used to override the template name. This is used for example in
the `get_description` method to render the description of the post using
the `post_body.html` template for the feed and the twitter card.

API-Fields
----------

There are some additional fields that can be fetched from the wagtail pages API:
* uuid - a unique identifier for the post
* visible_date - the date the post is visible, usually used for sorting
* comments_enabled - whether comments are enabled for this post
* cover_image_poster_url - a resized poster image URL for the Podlove Web Player
* body - the body stream field of the post
* html_overview - the rendered html of the overview section of the body (used in SPA themes)
* html_detail - the rendered html of the overview and detail section of the body (used in SPA themes)

Episode
=======

A special kind of post that has some additional fields and logic.

Specialized Post for podcast episodes with audio requirements.

.. code-block:: python

    class Episode(Post):
        podcast_audio = ForeignKey(Audio, on_delete=PROTECT)
        keywords = CharField(max_length=255)
        explicit = PositiveSmallIntegerField(choices=EXPLICIT_CHOICES)
        block = BooleanField(default=False)
        episode_number = PositiveIntegerField(null=True, blank=True)
        episode_type = CharField(choices=["full", "trailer", "bonus"], blank=True)
        season = ForeignKey(Season, null=True, blank=True)

**Key Features:**

- Requires ``podcast_audio`` to be published
- Inherits all Post functionality
- Additional iTunes metadata fields
- Optional publishing metadata for feeds: positive episode number, explicit
  episode type, and season assignment
- The selected season must belong to the parent podcast. Draft or parentless
  episodes defer this cross-object check until the parent exists.
- RSS GUIDs continue to use the episode UUID; episode numbers and seasons do
  not identify feed items

**Methods:**

- ``get_enclosure_url()``: Returns audio URL for RSS feed
- ``get_enclosure_size()``: Returns audio file size
- ``get_transcript_or_none()``: Returns associated transcript

**Properties:**

- ``podcast``: Parent Podcast instance

*************
Media Models
*************

Models for managing various media types with user ownership.

Audio
=====

Comprehensive audio file management with multiple format support.

.. code-block:: python

    class Audio(models.Model):
        user = ForeignKey(User)
        duration = DurationField()
        title = CharField(max_length=255)
        subtitle = CharField(max_length=255)

        # Format fields
        m4a = FileField(upload_to='cast_audio/m4a')
        mp3 = FileField(upload_to='cast_audio/mp3')
        oga = FileField(upload_to='cast_audio/oga')
        opus = FileField(upload_to='cast_audio/opus')

        data = JSONField()  # Metadata storage

**Key Methods:**

- ``create_duration()``: Calculates duration using ffprobe
- ``size_to_metadata()``: Caches file sizes
- ``get_file_size(format)``: Returns size for specific format
- ``get_chaptermark_data_from_file()``: Extracts embedded chapters

**Properties:**

- ``audio``: List of available formats for player
- ``chapters``: Chapter marks formatted for player
- ``uploaded_audio_files``: Iterator of available formats

ChapterMark
===========

Time-based chapters for audio navigation.

.. code-block:: python

    class ChapterMark(models.Model):
        audio = ForeignKey(Audio)
        start = TimeField()
        title = CharField(max_length=512)
        link = URLField(blank=True)
        image = URLField(blank=True)

**Features:**

- Defines navigable sections within audio
- Optional links and images per chapter
- Custom manager for bulk synchronization

Video
=====

Video file management with automatic poster generation.

.. code-block:: python

    class Video(models.Model):
        user = ForeignKey(User)
        title = CharField(max_length=255)
        original = FileField(upload_to='cast_video')
        poster = ImageField(upload_to='cast_video_poster')
        poster_seconds = FloatField(default=0)

**Key Methods:**

- ``create_poster()``: Generates thumbnail using ffmpeg
- ``get_mime_type()``: Returns MIME type from extension
- ``_get_video_dimensions()``: Extracts video dimensions

**Properties:**

- ``filename``: Original filename
- ``type``: Returns "video"

Image
=====

Extended Wagtail image model with user ownership.

.. code-block:: python

    class Image(AbstractImage):
        user = ForeignKey(User)

**Features:**

- Inherits Wagtail's image functionality
- Adds user ownership for filtering
- Automatic rendition generation

Gallery
=======

Collection of images for gallery displays.

.. code-block:: python

    class Gallery(models.Model):
        images = ManyToManyField('wagtailimages.Image')

**Methods:**

- ``create_renditions()``: Pre-generates image renditions

**Properties:**

- ``image_ids``: Set of associated image IDs

**Utility:**

- ``get_or_create_gallery()``: Reuses galleries with same images

File
====

Simple file storage with user association.

.. code-block:: python

    class File(models.Model):
        user = ForeignKey(User)
        original = FileField(upload_to='cast_files')

ItunesArtWork
=============

Podcast artwork storage for iTunes requirements.

.. code-block:: python

    class ItunesArtWork(models.Model):
        original = ImageField(upload_to='cast_itunes_artwork')
        original_height = PositiveIntegerField()
        original_width = PositiveIntegerField()

**************************
Content Enhancement Models
**************************

Models that add functionality to core content.

Transcript
==========

Multi-format transcripts for audio accessibility.

.. code-block:: python

    class Transcript(models.Model):
        audio = OneToOneField(Audio)
        podlove = FileField(upload_to='cast_transcript/podlove.json')
        vtt = FileField(upload_to='cast_transcript/vtt')
        dote = FileField(upload_to='cast_transcript/dote.json')

**Properties:**

- ``podlove_data``: Parsed Podlove format data
- ``dote_data``: Parsed DOTe format data
- ``podcastindex_data``: Converted to podcast index format

PostCategory
============

Category taxonomy for organizing posts.

.. code-block:: python

    class PostCategory(models.Model):
        name = CharField(max_length=255, unique=True)
        slug = SlugField(unique=True)

**Features:**

- Registered as Wagtail snippet
- Used for faceted search and filtering

*****************
Moderation Models
*****************

SpamFilter
==========

Machine learning spam detection for comments.

.. code-block:: python

    class SpamFilter(models.Model):
        name = CharField(max_length=128, unique=True)
        model = JSONField()  # Serialized NaiveBayes
        performance = JSONField()  # Metrics

**Class Methods:**

- ``comment_to_message(comment)``: Converts comment to trainable text
- ``get_training_data_comments()``: Gets comments for training
- ``get_default()``: Returns default filter instance

**Methods:**

- ``retrain_from_scratch()``: Rebuilds model from all comments

***************
Theme Models
***************

TemplateBaseDirectory
=====================

Site-wide theme configuration setting.

.. code-block:: python

    @register_setting
    class TemplateBaseDirectory(BaseSiteSetting):
        name = CharField(max_length=128, choices=get_choices())

**Utility Functions:**

- ``get_template_base_dir_choices()``: Available themes
- ``get_template_base_dir(request)``: Current theme

*******************
Repository Models
*******************

The repository pattern provides optimized data access with minimal queries.

Public import surface
=====================

Import repository helpers from ``cast.models.repository``.
The package exports the supported public names for repository classes,
serialization helpers, selected builder helpers, and repository type aliases.
The example below is a curated subset showing the most common imports, not the
full ``__all__`` surface.

.. code-block:: python

    from cast.models.repository import (
        BlogIndexContext,
        EpisodeFeedContext,
        FeedContext,
        PostDetailContext,
        PostQuerySnapshot,
        deserialize_audio,
        deserialize_blog,
        deserialize_episode,
        deserialize_image,
        deserialize_post,
        deserialize_renditions,
        deserialize_transcript,
        deserialize_video,
        serialize_audio,
        serialize_blog,
        serialize_episode,
        serialize_image,
        serialize_post,
        serialize_renditions,
        serialize_transcript,
        serialize_video,
    )

Additional public exports include builder helpers such as
``add_queryset_data``, ``data_for_blog_cachable``, and ``get_facet_choices``;
utility helpers such as ``cache_page_url`` and ``rendition_to_dict``; and type
aliases such as ``PostByID``, ``AudioById``, and ``RenditionsForPosts``.

The 0.2.54 cleanup removed the older alias names. Use the canonical names below
when upgrading existing code:

=========================  ==========================
Removed                    Replacement
=========================  ==========================
``QuerysetData``           ``PostQuerySnapshot``
``PostDetailRepository``   ``PostDetailContext``
``BlogIndexRepository``    ``BlogIndexContext``
``FeedRepository``         ``FeedContext``
``EpisodeFeedRepository``  ``EpisodeFeedContext``
``audio_to_dict``          ``serialize_audio``
``video_to_dict``          ``serialize_video``
``image_to_dict``          ``serialize_image``
``blog_to_dict``           ``serialize_blog``
``blog_from_data``         ``deserialize_blog``
``post_to_dict``           ``serialize_post``
``episode_to_dict``        ``serialize_episode``
``transcript_to_dict``     ``serialize_transcript``
=========================  ==========================

The removed aliases are not kept as compatibility shims. Importing them now
raises ``ImportError`` or ``AttributeError`` depending on how they are accessed.

PostQuerySnapshot
=================

Base repository for post querysets with prefetched relations.

**Contains:**

- Posts with all media relationships
- Image renditions
- User data
- URL information

PostDetailContext
====================

Optimized repository for single post pages.

**Features:**

- All data for rendering without additional queries
- Includes parent blog data
- Media with renditions

BlogIndexContext
===================

Repository for blog index pages with filtering.

**Features:**

- Filtered and paginated posts
- Facet counts for categories, tags, dates
- Optimized for list views

FeedContext
==============

Specialized repository for RSS/podcast feed generation.

**Optimizations:**

- Minimal data for feed rendering
- Efficient query patterns
- Supports both blog and podcast feeds

EpisodeFeedContext
==================

Per-episode context used while rendering podcast feed items.

**Contains:**

- Episode podcast audio object
- Optional transcript object for ``podcast:transcript`` output

*******************
Model Relationships
*******************

Page Hierarchy
==============

.. code-block:: text

    HomePage
    ├── Blog
    │   ├── Post
    │   └── Post
    └── Podcast
        ├── Episode
        └── Episode

Media Associations
==================

- **Post** ↔ **Audio/Video/Image/Gallery** (ManyToMany)
- **Episode** → **Audio** (ForeignKey, required)
- **Podcast** → **Season** (ForeignKey from Season, reusable per podcast)
- **Episode** → **Season** (ForeignKey, optional)
- **Audio** → **Transcript** (OneToOne)
- **Audio** → **ChapterMark** (OneToMany)
- **Gallery** ↔ **Image** (ManyToMany)

User Relationships
==================

- **Audio/Video/File/Image** → **User** (ForeignKey)
- **Post** → **User** (via Wagtail's owner)

Categorization
==============

- **Post** ↔ **PostCategory** (ManyToMany)
- **Post/Audio/Video** → **Tags** (TaggableManager)

******************
Special Behaviors
******************

Media Synchronization
=====================

Posts automatically sync media references from built-in StreamField media blocks
to ManyToMany relationships using the ``sync_media_ids()`` method. This happens
on save and ensures built-in image, gallery, video, and audio blocks are
properly associated for queries. Media references inside custom
``CAST_POST_BODY_BLOCKS`` blocks are not synced automatically.

Rendition Management
====================

Image renditions are automatically created based on usage context. The system supports:

- Regular image slots with configurable dimensions
- Gallery-specific renditions
- Bulk pre-generation for performance

Performance Optimization
========================

The repository pattern aggressively prefetches related data to minimize queries:

- Single query for post lists with all media
- Optimized feed generation
- Cached facet counts

Theme System
============

Templates are resolved through a flexible hierarchy:

1. Session-based theme selection
2. Blog-level configuration
3. Site-wide default
4. Built-in templates

Feed Support
============

Specialized repositories and methods optimize feed generation:

- Minimal queries for large feeds
- Proper caching headers
- Support for both RSS and podcast feeds
- Podcast feed caches include episode number, episode type, and season
  number/name so cached feed rendering remains query-free
