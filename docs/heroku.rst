Heroku
======

Install the heroku_ command line app
------------------------------------

At first you have to create an heroku account and install the heroku_ command line app.

Then creeate your app with the heroku client and make your newly created app the default app,
to avoid having to specify it for every heroku toolbelt call with "-a":


.. code-block:: shell

    heroku create --buildpack https://github.com/heroku/heroku-buildpack-python --region eu
    heroku git:remote -a <name-of-the-app>

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

MEDIA_ROOT
^^^^^^^^^^
MEDIA_ROOT in S3 wont work at the moment. I used a fork of django-imagekit where I
fixed an issue with S3 and always used my fork and forgot to create a pull request
for django-imagekit_. I didn't manage to get my fork installed on heroku_ because
django-cast requires django-imagekit so even if I put it in requirements/base.txt
it get's overwritten. Bad karma from not creating a PR in time is bad.

.. _`heroku`: https://devcenter.heroku.com/articles/getting-started-with-python
.. _`django-imagekit`: https://github.com/matthewwithanm/django-imagekit
