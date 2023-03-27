*********************
Django-Admin Commands
*********************

There are some management-commands bundled with django-cast. Most of them
are dealing with the management of media files.

* ``recalc_video_posters``: Recalculate the poster images for all videos.
* ``s3_backup``: Backup media files from S3 to local media root.
* ``s3_media_sizes``: Print the sizes of all media files on S3.
* ``s3_replace``: Replace paths on s3 with versions from local media root.
  This might be useful for videos for which you now have a better compressed
  version, but you don't want to generate a new name.
* ``s3_restore``: Restore media files from local media root to S3.
* ``s3_stale``: Print the paths of all media files on S3 that are not
  referenced in the database.
