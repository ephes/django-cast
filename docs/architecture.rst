Architecture Overview
=====================

This document describes the high-level architecture of Django Cast.

Django Cast is a blogging and podcasting application built on Django and Wagtail CMS.

High-Level Design
-----------------

Django Cast follows a layered architecture:

.. code-block:: text

    ┌─────────────────────────────────────────────────────┐
    │                   Frontend Layer                    │
    │         (Templates, JavaScript, HTMX)               │
    └─────────────────────────────────────────────────────┘
                             │
    ┌─────────────────────────────────────────────────────┐
    │                     API Layer                       │
    │         (REST Framework + Wagtail API v2)           │
    └─────────────────────────────────────────────────────┘
                             │
    ┌─────────────────────────────────────────────────────┐
    │                   Models Layer                      │
    │      (Django ORM - Wagtail Pages + Models)          │
    └─────────────────────────────────────────────────────┘
                             │
    ┌─────────────────────────────────────────────────────┐
    │                  Repository Layer                   │
    │     (QuerysetData, PostDetailRepository, etc.)      │
    └─────────────────────────────────────────────────────┘
                             │
    ┌─────────────────────────────────────────────────────┐
    │                  Database Layer                     │
    │              (PostgreSQL/SQLite)                    │
    └─────────────────────────────────────────────────────┘

Page Hierarchy
--------------

Cast uses Wagtail's page tree to organize content:

.. code-block:: text

    HomePage (cast.HomePage)
    ├── Blog (cast.Blog) - Index page for posts
    │   ├── Post (cast.Post) - Individual blog posts
    │   └── Post (cast.Post)
    └── Podcast (cast.Podcast) - Blog with podcast metadata (iTunes fields, etc.)
        ├── Episode (cast.Episode) - Post with audio enclosure
        └── Episode (cast.Episode)

- **Podcast**: A Blog subclass with extensive podcast metadata (iTunes categories, explicit content flags, etc.)
- **Episode**: A Post subclass that includes audio files which become enclosure elements in RSS feeds

Repository Pattern
------------------

The repository pattern sits between the database and Django models. It provides an abstraction layer that returns dictionaries (not model instances) that are JSON-serializable. This enables caching between the database queries and model instantiation.

Flow::

    Database → Django ORM/Raw SQL → Repository → Dict → JSON Cache → Dict → Django Models → Template

Key Repository Classes
~~~~~~~~~~~~~~~~~~~~~~

**QuerysetData**
  Base class that converts querysets to dictionaries with prefetch optimization.

**PostDetailRepository**
  Fetches single post data with all relations in minimal queries.

**FeedRepository**
  Optimized for RSS/podcast feed generation.

**BlogIndexRepository**
  Handles blog index pages with pagination.

The repositories:

- Execute optimized queries (ORM or raw SQL)
- Return dictionary structures
- Enable JSON caching of query results
- Allow dynamic model reconstruction from cached data

Models Architecture
-------------------

Cast models are organized into:

1. **Page Models** (``models/pages.py``):

   - ``HomePage``: Site root
   - ``Blog``: Container for posts
   - ``Post``: Blog entries with StreamField content
   - ``Podcast``: Blog subclass with iTunes metadata, categories, etc.
   - ``Episode``: Post subclass with audio fields for RSS enclosures

2. **Media Models**:

   - ``Image``: User-owned images
   - ``Audio``: Audio files with duration and metadata
   - ``Video``: Video files with poster frames
   - ``Gallery``: Collection of images
   - ``ChapterMark``: Timestamps for podcast chapters
   - ``Transcript``: Text for audio/video

3. **Moderation** (``models/moderation.py``):

   - ``SpamFilter``: Naive Bayes spam detection

StreamField Structure
---------------------

Posts use a two-section StreamField:

.. code-block:: python

    body = StreamField([
        ("overview", blocks.StreamBlock([...])),
        ("detail", blocks.StreamBlock([...])),
    ])

This allows showing just the overview on index pages and full content on detail pages.

Available block types include:

- Text blocks (heading, paragraph, code)
- Media blocks (image, gallery, video, audio)
- Embed blocks (HTML, external embeds)

Performance Optimization
------------------------

Query Optimization
~~~~~~~~~~~~~~~~~~

The repository pattern minimizes database queries through:

1. **select_related**: For one-to-many foreign keys
2. **prefetch_related**: For many-to-many relations
3. **Bulk operations**: For rendition creation

Caching
~~~~~~~

- **Repository cache**: JSON-serialized query results (filesystem cache)
- **Rendition cache**: Generated image sizes
- **Feed cache**: Generated RSS/XML feeds

Media Handling
--------------

Media Pipeline:

1. **Upload**: Via Wagtail admin or API
2. **Storage**: Django storage backend (local or S3)
3. **Processing**:

   - Images: Wagtail renditions
   - Audio: Duration extraction
   - Video: Poster generation

4. **Delivery**: Direct or via CDN

API Architecture
----------------

Cast provides:

1. **Wagtail API v2**: Page content access
2. **Custom REST endpoints**: Media uploads, search
3. **Feed endpoints**: RSS/podcast XML

Note: The REST Framework serializers are not performance-optimized. Performance optimization happens at the repository and feed generation level.

Frontend Components
-------------------

- **Templates**: Django/Wagtail templates
- **JavaScript**:

  - Build system: Vite
  - Podcast player: Podlove (Vue.js app wrapped in web component)
  - Web components: Gallery viewer (used by GalleryWithLayout blocks)
  - Interactivity: HTMX

- **Styling**: CSS (fully customizable via themes)

Code Organization
-----------------

.. code-block:: text

    src/cast/
    ├── api/              # REST API
    ├── blocks.py         # StreamField blocks
    ├── feeds.py          # RSS/podcast feeds
    ├── management/       # Django commands
    ├── migrations/       # Database migrations
    ├── models/           # Model definitions
    ├── static/           # Built assets
    ├── templates/        # Django templates
    ├── views/            # Django views
    └── wagtail_hooks.py  # Admin customizations

Extension Points
----------------

1. **StreamField Blocks**: Add new content types in ``blocks.py``
2. **Themes**: Override templates or install theme packages (e.g., cast-vue, cast-bootstrap5)
3. **Management Commands**: Add CLI tools
4. **API Endpoints**: Extend REST API

Theme System
------------

Themes provide complete control over the frontend:

- **Template replacement**: Override any/all templates
- **Full customization**: Use any CSS framework or approach
- **SPA support**: Can function as headless CMS (e.g., cast-vue uses Vue.js SPA)
- **Package distribution**: Themes as PyPI packages

The theme system allows everything from minor template tweaks to complete frontend replacements.

Deployment
----------

Typical deployment:

- **Application**: Django app server
- **Static files**: Served by Django with whitenoise
- **Media files**: CDN or Django direct serving
- **Database**: PostgreSQL (recommended) or SQLite
- **Caching**: Filesystem cache for repository results

Security
--------

- **User isolation**: Users see only their own media
- **Spam filtering**: Naive Bayes for comments
- **CSRF protection**: Django middleware
- **XSS prevention**: Template auto-escaping
