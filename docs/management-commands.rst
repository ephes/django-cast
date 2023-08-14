*********************
Django-Admin Commands
*********************

.. _cast_management_commands:

There are some management-commands bundled with django-cast. Most of them
are dealing with the management of media files.

* ``recalc_video_posters``: Recalculate the poster images for all videos.
* ``media_backup``: Backup media files from production to backup storage backend (requires Django >= 4.2).
* ``media_sizes``: Print the sizes of all media files stored in the production storage backend (requires Django >= 4.2).
* ``media_replace``: Replace files on production storage backend with versions from local file system (requires Django >= 4.2).
  This might be useful for videos for which you now have a better compressed
  version, but you don't want to generate a new name.
* ``media_restore``: Restore media files from backup storage backend to production storage backend (requires Django >= 4.2).
* ``media_stale``: Print the paths of all media files stored in the production storage backend that are not
  referenced in the database (requires Django >= 4.2).
