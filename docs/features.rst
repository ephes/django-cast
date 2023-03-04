########
Features
########

********
Frontend
********

Pagination
==========

The blog index page comes with pagination support. You can set the
number of posts per page using the `POST_LIST_PAGINATION` setting.

If there are more then 3 pages, there will be a "..." in the pagination.
If there are more then 10 pages, there will be two "..." in the pagination.

************
Django-Admin
************

The file sizes of an audio object are cached automatically. But
for old audio objects there's an admin action where you can update
the file size cache for all associated audio files.

.. image:: images/cache_file_sizes_admin_action.png
  :width: 800
  :alt: Show the admin action to update the file size cache

.. include:: social-media.rst

.. include:: spamfilter.rst

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
