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

You can set a cover image for a post. For posts that don't have a cover image,
I usually generate one using the `shot-scraper <https://github.com/simonw/shot-scraper>`_ tool:

.. code-block:: shell

    pipx install shot-scraper
    shot-scraper install  # installs chromium headless
    shot-scraper shot https://wersdoerfer.de/blogs/ephes_blog/ -w 800 -h 400 --retina --quality 60

This will generate a screenshot of the blog post and save it as a jpeg. But you can also
use png. It is also possible to set a separate alt text for the cover image.

Tags
====

You can add tags to a post. Tags can be used to filter posts on the blog index page.

Body
====

The body of a post is a streamfield. You can add different types of blocks to the body of a post.

Overview
--------

Overview blocks are used to display a summary of the post on the blog index page or
in feeds.

Detail
------

Detail blocks are used to display the full content of the post. Usually it is shown
on the post detail page.

Types of Blocks
---------------

Following types of blocks are available for the body of a post:

- Heading
- Paragraph - Rich Text which can include headings, images, links, etc.
- :ref:`Image <image_overview>` - A single image
- :ref:`Gallery <gallery_overview>` with Layout - A gallery of images with different layout options
- Embed - Embed a video or other content from a URL
- :ref:`Video <video_overview>`
- :ref:`Audio <audio_overview>` - Displayed using the Podlove Web Player
- Code - Code block with syntax highlighting
