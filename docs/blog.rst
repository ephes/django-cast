.. _blog_overview:

****
Blog
****

Description
===========

The `description` field is used to populate the `description` attribute in the feed.
And it is also used in the default templates to display a short description of the blog
on the blog index page.

Email
=====

Contact address for the blog.

Author
===========

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

Promote > NoIndex
=================

If you set the custom `BooleanField` field named `noindex` on a Blog-Page
using the Wagtail or Django-Admin interface, the Page and all its subpages
will be excluded from being indexed by search engines.
