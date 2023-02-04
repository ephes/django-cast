Features
========

Django-Admin
------------

The file sizes of an audio object are cached automatically. But
for old audio objects there's an admin action where you can update
the file size cache for all associated audio files.

.. image:: images/cache_file_sizes_admin_action.png
  :width: 800
  :alt: Show the admin action to update the file size cache

Blog
----

Blog / Podcast Author
~~~~~~~~~~~~~~~~~~~~~

You can define a custom `CharField` field named `author` on a Blog-Page
using the Wagtail or Django-Admin interface. This field is then used to
populate following attributes in the feed:

- `itunes:author`
- `itunes:name`
- `author_name` in atom feed

If the `author`-field is not set `blog.owner.get_full_name()` is used instead.
