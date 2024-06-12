.. _post_overview:

****
Post
****

Posts are Wagtail pages that have a :ref:`blog <blog_overview>` page as a parent.

Visible Date
============

You can set the `visible_date` of a post, which will be showed in templates
and used for sorting posts shown on the blog index page.

Cover Image
===========

The cover image for a post is used for meta tags like `twitter:image` or
`og:image`. But you can also use it in the templates for the blog index page
or the post detail page. If you set `cover_alt_text`, it can be used as the
`alt` attribute of the cover image.

For posts without a cover image, the :ref:`blog <blog_overview>`’s cover
image will be used. Alternatively, I often generate one using the
`shot-scraper <https://github.com/simonw/shot-scraper>`_ tool:

.. code-block:: shell

    pipx install shot-scraper
    shot-scraper install  # installs chromium headless
    shot-scraper shot https://wersdoerfer.de/blogs/ephes_blog/ -w 800 -h 400 --retina --quality 60

This will generate a screenshot of the blog post and save it as a jpeg. But you can also
use png. It is also possible to set a separate alt text for the cover image.

Tags
====

You can add tags to a post. Tags can be used to filter posts on the blog index page.

Promote > Title
===============

There is a field called `title` in the promote tab of the Wagtail admin which is used to
set the title of the post for search engine results as the clickable headline. This will
also be used for the `og:title` and `twitter:title` meta tags.

Promote > Description
=====================

The `description` field in the promote tab of the Wagtail admin is used to set the description
of the post for search engine results. This will also be used for the `og:description` and
`twitter:description` meta tags.

Body
====

The body of a post is a `StreamField <https://docs.wagtail.org/en/stable/topics/streamfield.html>`_.
You can add different types of blocks to the body of a post. There are two types of blocks you can
add to the body of a post:

1. Overview
-----------

Overview blocks are used to display a summary of the post on the blog index page or
in feeds.

2. Detail
---------

Detail blocks are used to display the full content of the post. Usually it is shown
on the post detail page.

Types of Blocks
---------------

Inside the Overview and Detail blocks following types of blocks are available:

- Heading
- Paragraph - Rich Text which can include headings, images, links, etc.
- :ref:`Image <image_overview>` - A single image
- :ref:`Gallery <gallery_overview>` with Layout - A gallery of images with different layout options
- Embed - Embed a video or other content from a URL
- :ref:`Video <video_overview>`
- :ref:`Audio <audio_overview>` - Displayed using the Podlove Web Player
- Code - Code block with syntax highlighting
