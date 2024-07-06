.. _blog_overview:

****
Blog
****

Title
=====

The `title` field is used to populate the `title` attribute in the feed. And
it is also used in the default templates to display the title of the blog on
the blog index page.

Subtitle
========

The `subtitle` field is used to populate the `subtitle` attribute on the podlove
player.

Description
===========

The `description` field is used to populate the `description` attribute in the feed.
And it is also used in the default templates to display a short description of the blog
on the blog index page.

Email
=====

Contact address for the blog.

Author
======

If you set the custom `CharField` field named `author` on a Blog-Page
using the Wagtail or Django-Admin interface, the content of this field
is then used to populate following attributes in the feed:

- `itunes:author`
- `itunes:name`
- `author_name` in atom feed

Template Base Dir
=================

The `template_base_dir` field is used to specify the base directory for the
templates used to render the blog. It's basically a theme switcher.

Cover Image
===========
The `cover_image` field is used to specify the cover image for the blog.
If posts have no cover image, the blog cover image will be used as a fallback.
There's a `cover_alt_text` field to specify the alt text for the cover image.

Promote > Title
===============
This title is show in search engine results linking to the blog.

Promote > Description
=====================
This description is show in search engine results linking to the blog.

Promote > NoIndex
=================

If you set the custom `BooleanField` field named `noindex` on a Blog-Page
using the Wagtail or Django-Admin interface, the Page and all its subpages
will be excluded from being indexed by search engines.
