****
Blog
****

Blog / Podcast Author
=====================

If you set the custom `CharField` field named `author` on a Blog-Page
using the Wagtail or Django-Admin interface, the content of this field
is then used to populate following attributes in the feed:

- `itunes:author`
- `itunes:name`
- `author_name` in atom feed

If the `author`-field is not set `blog.owner.get_full_name()` is used instead.

Blog / NoIndex
==============

If you set the custom `BooleanField` field named `noindex` on a Blog-Page
using the Wagtail or Django-Admin interface, the Page and all its subpages
will be excluded from being indexed by search engines.
