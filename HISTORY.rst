.. :changelog:

History
-------

0.1.28 (2019-06-03)
+++++++++++++++++++

* Added some analytics support: import your access.log and view dashboard with hits/day,week
* Fixed pub_date bug, leading to safari not being able to update posts + some tests
* Use local web-player and subscribe button (didn't improve performance, though :( )
* Fixed detail content not included in feed (shownotes were missing) bug
* Added some deployment documentation for heroku, ec2 and docker
* Overwritable block for detail link in post list template + documentation

0.1.27 (2019-05-27)
+++++++++++++++++++

* Extended documentation
* It's now possible to mark content as "for post detail page" only
* Changed documentation to work with comments
* Fixed comments dependencies in setup.py

0.1.26 (2019-05-23)
+++++++++++++++++++

* Bugfix: i18n should now work, finally!!1 duh

0.1.25 (2019-05-23)
+++++++++++++++++++

* Bugfix: i18n should now work, finally
* Bugfix: Allow empty chaptermarks text field + test

0.1.24 (2019-05-22)
+++++++++++++++++++

* Use blog.email as itunes:email instead of blog.user.email
* Added author field to have user editable author name
* Translation should now work since locale dir is included in MANIFEST.in
* Include documentation in package
* Use visible_date as pubDate for feed and sort feed by -visible_date instead of -pub_date

0.1.23 (2019-05-16)
+++++++++++++++++++

* Comment en/disabling per site/blog/post
* Fix duration extraction and small issues with the installation docs @jnns
* Support for comments by @oryon-dominik

0.1.22 (2019-04-28)
+++++++++++++++++++

* Use proper time field for chaptermark start instead of char
* Improved test coverage
* Improved video dimension handling for handbrake generated portrait videos

0.1.21 (2019-04-24)
+++++++++++++++++++

* Fixed package dependencies
* Better release docs

0.1.20 (2019-04-24)
+++++++++++++++++++

* Fixed version history
* Better release docs

0.1.19 (2019-04-24)
+++++++++++++++++++

* Added fulltext search
* Added filtering by date + some faceted navigation support
* use overwritable template block for feeds section (could be used for podlove subscribe button)

0.1.18 (2019-04-18)
+++++++++++++++++++

* Fixed broken update view due to empty chaptermarks + test
* Fixed two image/video javascript bugs

0.1.17 (2019-04-15)
+++++++++++++++++++

* Added chaptermarks feature
* Duration is now displayed correctly in podlove player
* If an audio upload succeeded, add the uploaded element to podcast audio select form

0.1.16 (2019-03-23)
+++++++++++++++++++

* Finally, rtfd is working again, including screencast

0.1.15 (2019-03-23)
+++++++++++++++++++

* Trying again... rtfd still failing

0.1.14 (2019-03-23)
+++++++++++++++++++

* Added rtfd configuration file to be able to use python 3 :/

0.1.13 (2019-03-22)
+++++++++++++++++++

* Release to update read the docs

0.1.12 (2019-03-22)
+++++++++++++++++++

* Improved installation documentation

0.1.11 (2019-03-21)
+++++++++++++++++++

* Fixed requirements for package

0.1.10 (2019-03-21)
+++++++++++++++++++

* Dont limit the number of items in feed (was 5 items)
* Workaround for ogg files (ending differs for Audio model field name)
* Added opus format to Audio model

0.1.9 (2019-03-12)
++++++++++++++++++

* Added some podcast specific fields to post edit form
* If two audio uploads have the same name, add them to the same model instance
* Added audio file support for post edit form
* Show which audio files already were uploaded

0.1.8 (2019-02-28)
++++++++++++++++++

* Added support for m4v and improved dimension detection for iOS videos
* Added some tests for different video sources

0.1.7 (2019-02-28)
++++++++++++++++++

* forgot linting

0.1.6 (2019-02-28)
++++++++++++++++++

* Use filepond for media uploads (images video)
* Improved portrait video support
* Get api prefix programatically from schema
* Fixed link to podcast in itunes (was feed, now it's post list)
* Set visible date to now if it's not set
* use load static instead of staticfiles (deprecated)
* Fixed language displayed in itunes (you have to set it in base.py in settings)
* Dont try to be fancy, just display a plain list of feed on top of post list site (and podcast feeds only if blog.is_podcast is True)

0.1.5 (2018-11-21)
++++++++++++++++++

* basic feed support (rss/atom) for podcasts
* travis now runs tests with ffprobe, too
* documentation fixes from @SmartC2016 and @oryon-dominik

0.1.4 (2018-11-18)
++++++++++++++++++

* Include css via cast_base.html
* audio fixes

0.1.3 (2018-11-17)
++++++++++++++++++

* Fixed css/static icons
* Merged pull request from SmartC2016 to fix javascript block issue
* Added some documentation

0.1.2 (2018-11-08)
++++++++++++++++++

* Added some requirements
* Release Documentation

0.1.1 (2018-11-07)
++++++++++++++++++

* Travis build is ok.

0.1.0 (2018-11-05)
++++++++++++++++++

* First release on PyPI.
