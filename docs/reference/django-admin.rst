************
Django-Admin
************

Django Cast registers several models in the Django admin with custom actions
and configuration.

Admin Actions
=============

Cache file sizes (Audio)
-------------------------

The file sizes of audio objects are cached in metadata for display purposes.
New uploads are cached automatically, but for older audio objects you can
update the cache in bulk:

1. Go to Django Admin > Audio
2. Select the audio objects to update
3. Choose "Cache file sizes" from the action dropdown

.. image:: ../images/cache_file_sizes_admin_action.png
   :width: 800
   :alt: Show the admin action to update the file size cache

Retrain spam filter (SpamFilter)
---------------------------------

The Naive Bayes spam filter can be retrained from scratch using comments
that have been manually classified as spam or ham:

1. Go to Django Admin > Spam Filters
2. Select the spam filter to retrain
3. Choose "Retrain model from scratch using marked comments" from the action dropdown

The admin list view shows precision and recall metrics for each filter,
helping you assess filter quality.

Wagtail Admin Customizations
=============================

Django Cast extends the Wagtail admin with custom menu items and editor
integrations.

Media Menu Items
-----------------

Four menu items are added to the Wagtail admin sidebar for managing media and podcast credits:

- **Audio** - List, add, edit, and delete audio files with chapter marks
- **Video** - List, add, edit, and delete video files with poster images
- **Transcript** - List, add, edit, and delete transcripts
- **Contributors** - List, add, edit, and delete reusable podcast contributors

Each menu item is permission-aware and only appears for users with the
appropriate permissions on the respective model.

Contributors Management
------------------------

Contributors are registered as Wagtail snippets and are also linked directly
from the Wagtail admin sidebar. This gives editors a top-level **Contributors**
entry instead of requiring them to navigate through **Snippets** first.
Contributor snippets include a default episode role and ordered profile links.
When an editor adds a contributor to an episode, the episode assignment starts
with that role and the first ordered profile link.

Tags Management
----------------

Tags (from ``django-taggit``) are registered as a Wagtail snippet, providing
a CRUD interface for managing tags directly in the Wagtail admin under
the Snippets menu.

Season Management
-----------------

Podcast seasons are regular Django models scoped to a single podcast. They are
available in the Django admin for basic CRUD and can be selected from episode
editing when assigning podcast publishing metadata.

Editor Integration
-------------------

Audio and video chooser URLs are injected into the Wagtail page editor,
enabling the audio and video chooser modals when editing StreamField
content blocks.

Page Link Caching
------------------

Django Cast registers a custom rich text link handler that caches page
URLs. This improves performance when rendering pages with many internal
links by avoiding repeated database lookups.
