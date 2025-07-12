################
Blogs and Posts
################

Django Cast organizes content using Wagtail's page hierarchy. Blogs serve as containers for posts, providing a structured way to publish and organize your content.

.. _blog_overview:

*****
Blogs
*****

A Blog is an index page that contains and displays a collection of posts. It serves as both a container and a listing page for your content.

Blog Fields
===========

Title
-----

The `title` field serves multiple purposes:

- Displays as the blog name on the index page
- Populates the `title` attribute in RSS/Atom feeds
- Used in page titles and breadcrumbs

Subtitle
--------

The `subtitle` field is used to populate the `subtitle` attribute on the podlove player when the blog contains podcast episodes.

Description
-----------

The `description` field:

- Populates the `description` attribute in feeds
- Displays on the blog index page in default templates
- Provides context for search engines

Email
-----

Contact address for the blog. This is used in feeds and can be displayed in templates.

Author
------

The `author` field identifies the blog owner and populates several feed attributes:

- `itunes:author`
- `itunes:name`
- `author_name` in Atom feeds

Template Base Dir
-----------------

The `template_base_dir` field acts as a theme switcher, allowing you to:

- Select different visual themes for your blog
- Override default templates
- Customize the look without code changes

For more information, see :doc:`/features/themes`.

Cover Image
-----------

The blog's cover image serves as:

- Default social media preview image for the blog
- Fallback for posts without their own cover image
- Visual identity for your blog

The `cover_alt_text` field provides accessibility text for screen readers.

SEO Settings
============

Promote > Title
---------------

The SEO title shown in search engine results linking to the blog. If not set, the main title is used.

Promote > Description
---------------------

The meta description shown in search engine results. This should be a compelling summary that encourages clicks.

Promote > NoIndex
-----------------

When the `noindex` field is checked:

- The blog and all its subpages are excluded from search engines
- Useful for private or staging blogs
- Inherits to all child posts

Comments
========

The `comments_enabled` field controls whether commenting is allowed on posts within this blog. Individual posts can override this setting. For more information about comments and spam filtering, see :doc:`/features/comments`.

.. _post_overview:

*****
Posts
*****

Posts are individual content pages that belong to a blog. They support rich content through Wagtail's StreamField system.

Post Fields
===========

Basic Information
-----------------

**Title**
  The post's headline, displayed prominently on both index and detail pages.

**Slug**
  URL-friendly version of the title. Auto-generated but can be customized.

**Visible Date**
  Controls when the post appears publicly and how it's sorted on the blog index. Useful for scheduling future posts or backdating content.

Cover Image
-----------

Each post can have its own cover image used for:

- Social media previews (Open Graph and Twitter cards)
- Visual element on blog index pages
- Hero image on post detail pages

The `cover_alt_text` field ensures accessibility.

If no cover image is set, the parent blog's cover image is used as a fallback.

**Tip**: Generate cover images using `shot-scraper <https://github.com/simonw/shot-scraper>`_:

.. code-block:: shell

    uvx install shot-scraper
    shot-scraper install  # installs chromium headless
    shot-scraper shot https://example.com/blog/my-post/ -w 800 -h 400 --retina --quality 60

Organization
------------

**Categories**
  Major topic areas for organizing posts. Posts can belong to multiple categories.

**Tags**
  More specific topics for fine-grained organization and filtering.

SEO Settings
------------

**Promote > Title**
  Custom title for search results and social media. Used for `og:title` and `twitter:title` meta tags.

**Promote > Description**
  Meta description for search results. Used for `og:description` and `twitter:description` meta tags.

Content Structure
=================

Posts use a StreamField with two main sections:

Overview Section
----------------

The overview section contains content that appears:

- On the blog index page
- In RSS/Atom feeds (both overview and detail sections are included)
- As excerpts in search results

Use this for summaries, key points, or teasers that encourage readers to click through.

Detail Section
--------------

The detail section contains the full article content that appears only on the post's individual page. This is where your main content goes.

Available Content Blocks
------------------------

Both sections support these block types:

- **Heading**: Section headers for organization
- **Paragraph**: Rich text with formatting, links, and inline images
- **Image**: Single responsive images with captions
- **Gallery**: Multiple images with lightbox functionality
- **Embed**: External content (YouTube, Twitter, etc.)
- **Video**: Self-hosted video files
- **Audio**: Audio files with the Podlove Web Player
- **Code**: Syntax-highlighted code blocks

For detailed information about content blocks, see :doc:`/content/streamfield`.

Media in Posts
==============

Posts automatically track all media used within them:

- Images are extracted from image blocks and galleries
- Videos from video blocks
- Audio from audio blocks

This enables:

- Efficient media management
- Bulk operations on post media
- Performance optimization through prefetching

Comments
--------

Individual posts can override the blog's comment settings. Use this to:

- Disable comments on specific posts
- Enable comments only for certain content

Publishing Workflow
===================

Draft Management
----------------

1. Create posts as drafts to work on them over time
2. Use Wagtail's preview feature to see how they'll look
3. Schedule publication using the visible date
4. Publish when ready

Scheduling Posts
----------------

To schedule a post for future publication:

1. Set the visible date to a future date/time
2. Publish the post (it won't appear publicly yet)
3. The post becomes visible automatically at the specified time

URL Structure
=============

Posts follow this URL pattern:

.. code-block:: text

    /blog-slug/post-slug/

For example:

- Blog: "Tech Blog" (slug: `tech-blog`)
- Post: "Django Best Practices" (slug: `django-best-practices`)
- URL: `/tech-blog/django-best-practices/`
