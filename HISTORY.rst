.. :changelog:

History

0.1.9 (2018-03-12)
++++++++++++++++++

* Added some podcast specific fields to post edit form
* If two audio uploads have the same name, add them to the same model instance
* Added audio file support for post edit form
* Show which audio files already were uploaded

0.1.8 (2018-02-28)
++++++++++++++++++

* Added support for m4v and improved dimension detection for iOS videos
* Added some tests for different video sources

0.1.7 (2018-02-28)
++++++++++++++++++

* forgot linting

0.1.6 (2018-02-28)
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
