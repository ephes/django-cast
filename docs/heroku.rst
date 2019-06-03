Heroku
======

Install the heroku_ command line app
------------------------------------

At first you have to create an heroku account and install the heroku_ command line app.

Then create your app with the heroku client and make your newly created app the default app,
to avoid having to specify it for every heroku toolbelt call with "-a":


.. code-block:: shell

    heroku create --buildpack https://github.com/heroku/heroku-buildpack-python --region eu
    heroku git:remote -a <name-of-the-app>

Use S3 for storing media files
------------------------------

You probably want to use S3 to store your media files (user uploaded content, images for blog
posts etc). We use django-imagekit_ for responsive images and there is some incompatibility
between boto_ and django-imagekit_ keeping it from working out of the box. Luckily there's a
workaround. At this custom storage class to your "config/settings/production.py" file and use
it:

.. code-block:: shell

	import os
	from tempfile import SpooledTemporaryFile
	...

	class CustomS3Boto3Storage(S3Boto3Storage):
		"""
		This is our custom version of S3Boto3Storage that fixes a bug in
		boto3 where the passed in file is closed upon upload.

		https://github.com/boto/boto3/issues/929
		https://github.com/matthewwithanm/django-imagekit/issues/391
		"""

		location = "media"
		file_overwrite = False
		default_acl = "public-read"

		def _save_content(self, obj, content, parameters):
			"""
			We create a clone of the content file as when this is passed to boto3
			it wrongly closes the file upon upload where as the storage backend
			expects it to still be open
			"""
			# Seek our content back to the start
			content.seek(0, os.SEEK_SET)

			# Create a temporary file that will write to disk after a specified size
			content_autoclose = SpooledTemporaryFile()

			# Write our original content into our copy that will be closed by boto3
			content_autoclose.write(content.read())

			# Upload the object which will auto close the content_autoclose instance
			super(CustomS3Boto3Storage, self)._save_content(
				obj, content_autoclose, parameters
			)

			# Cleanup if this is fixed upstream our duplicate should always close
			if not content_autoclose.closed:
				content_autoclose.close()

	...
	DEFAULT_FILE_STORAGE = "config.settings.production.CustomS3Boto3Storage"


Using S3 in a non-default region
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If you want to use S3 in the region "eu-central-1" you have to set some additional parameters
in your "config/settings/production.py":

.. code-block:: shell

	AWS_AUTO_CREATE_BUCKET = True
	AWS_S3_REGION_NAME = 'eu-central-1'  # if your region differs from default
	AWS_S3_SIGNATURE_VERSION = 's3v4'
	AWS_S3_FILE_OVERWRITE = True

Using cloudfront as CDN
^^^^^^^^^^^^^^^^^^^^^^^

If you want to deliver your media files via cloudfront there's an additional option you'll
have to set:

.. code-block:: shell

	AWS_S3_CUSTOM_DOMAIN = env('CLOUDFRONT_DOMAIN')

Set the configuration variables for heroku_
-------------------------------------------

Now we have to setup some heroku specific stuff. For some of the addons you might have to
add credit card information to your heroku account:

.. code-block:: shell

    heroku addons:create heroku-postgresql:hobby-dev
    heroku pg:backups schedule --at '02:00 Europe/Berlin' DATABASE_URL
    heroku addons:create heroku-redis:hobby-dev
    heroku addons:create mailgun:starter
    heroku config:set PYTHONHASHSEED=random
    heroku config:set WEB_CONCURRENCY=4
    heroku config:set DJANGO_DEBUG=False
    heroku config:set DJANGO_SETTINGS_MODULE=config.settings.production
    heroku config:set DJANGO_SECRET_KEY="$(openssl rand -base64 64)"
    heroku config:set DJANGO_ADMIN_URL="$(openssl rand -base64 4096 | tr -dc 'A-HJ-NP-Za-km-z2-9' | head -c 32)/"
    # use your own app name here..
    heroku config:set DJANGO_ALLOWED_HOSTS=<your_app_name>.herokuapp.com
    heroku config:set DJANGO_AWS_ACCESS_KEY_ID=<your_aws_key_id>
    heroku config:set DJANGO_AWS_SECRET_ACCESS_KEY=<your_aws_access_key>
    heroku config:set DJANGO_AWS_STORAGE_BUCKET_NAME=s3.foobar.com
    heroku config:set MAILGUN_DOMAIN=mg.foobar.com
    heroku config:set MAILGUN_API_KEY=key-<your_mailgun_key>
    heroku config:set MAILGUN_SENDER_DOMAIN=mg.foobar.com
    heroku config:set SENTRY_DSN=<your_sentry_dsn>

Deploy your project to heroku_
------------------------------

After setting all those configuration variables, you should be able to deploy your project
to heroku:

.. code-block:: shell

    git push heroku master

And create a superuser for your production system:

.. code-block:: shell

    heroku run python manage.py createsuperuser

Finally you should be able to check your deployment and open the website:

.. code-block:: shell

    heroku run python manage.py check --deploy
    heroku open

Use your own domain name with heroku
------------------------------------

Just follow the instructions on the custom-domains_ help site at heroku_.

.. _custom-domains: https://devcenter.heroku.com/articles/custom-domains

Caveats
-------

Static Files
^^^^^^^^^^^^
I couldn't get serving static files to work with amazon S3. One problem was that
DJANGO_AWS_STORAGE_BUCKET_NAME in the STATIC_URL setting seems to get ignored by the
static templatetag resulting in a permanent redirect error page from S3. And the
other problem is that S3 didn't support https (broken certificate). But all static
urls are https by default, so this didn't work either. Maybe you can fix that by using
a cloudfront distribution etc. but using whitebox to serve static files worked out of
the box.

SSL
^^^
You need to upload certificates to heroku_. Quite cumbersome.

.. _`heroku`: https://devcenter.heroku.com/articles/getting-started-with-python
.. _`django-imagekit`: https://github.com/matthewwithanm/django-imagekit
.. _`boto`: https://boto3.amazonaws.com/v1/documentation/api/latest/index.html
