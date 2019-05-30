Deployment
**********

Here we describe how to deploy a project named "foobar" to production. We are using
cookiecutter-django_ for convenience, but this should also be possible with other project
bootstrapping mechanisms.

Locally
=======

Install virtualenvwrapper_ and create a virtual environment for your project:

.. code-block:: shell

    mkvirtualenv -p /usr/local/bin/python3 foobar

Install cookiecutter_ into your newly create virtual environment:

.. code-block:: shell

    pip install cookiecutter

Use the django cookiecutter template to bootstrap your project:

.. code-block:: shell

    cookiecutter https://github.com/pydanny/cookiecutter-django

Don't forget to activate the options for Docker or Heroku if you plan to use them. And
set the "use whitenoise" configutation option to "yes" because this will get your static
file serving on heroku work without any additional config. Saying "no" to this, will
try to use aws S3, which I couldn't get to work (see below).

Enter your new project directory and checkin your first commit:

.. code-block:: shell

    cd foobar
    git init
    git add .
    git commit -m "first commit"

Optionally you can associate your project dir with a github repository (change
url to match your username/reponame):

.. code-block:: shell

    git remote add origin git@github.com:your_username/foobar.git
    git push -u origin master

Running the App locally
-----------------------

You could also use docker for this, but for now let's run the development
server locally. At first, add the "django-cast" requirement to your base.txt
requirements file and then install all the required packages into your virtualenv:

.. code-block:: shell

    echo "django-cast" >> requirements/base.txt
    pip install -r requirements/local.txt


You should already have a locally installed postgres server up and running.
Ok, now let's create the required database user, the database and all its tables.
It's also very useful to create a django superuser right away:

.. code-block:: shell

    createdb foobar;createuser foobar; psql -d foobar -c "GRANT ALL PRIVILEGES ON DATABASE foobar to foobar;"
    ./manage.py migrate
    ./manage.py createsuperuser


Now you should be able to start your development server locally and see an empty page:

.. code-block:: shell

    ./manage.py runserver_plus 0:8000
    open http://localhost:8000/

Open only works on mac OS, but you can just point your browser to this url. You should be able
to sign in with your superuser account in the django admin. If you want to sign in regularily,
you have to paste the confirmation url shown on the dev-server console when you try to sign in.

Mailgun
=======

If you use mailgun_ as an email service you have to register a mailgun account and set up your
dns records accordingly. One caveat: If you use the eu region you have to change your base api
url in "config/settings/production.py" to:

.. code-block:: python

    "MAILGUN_API_URL": env("MAILGUN_API_URL", default="https://api.eu.mailgun.net/v3"),

Static Files
============

I couldn't get serving static files to work with amazon S3. One problem was that
DJANGO_AWS_STORAGE_BUCKET_NAME in the STATIC_URL setting seems to get ignored by the
static templatetag resulting in a permanent redirect error page from S3. And the
other problem is that S3 didn't support https (broken certificate). But all static
urls are https by default, so this didn't work either. Maybe you can fix that by using
a cloudfront distribution etc. but using whitebox to serve static files worked out of
the box.

Sentry
======

This is the place where tracebacks that occured on the production system get recorded.
You'll need to signup for an account.

Amazon S3
=========

You'll probably use S3 for storing uploaded files and for your MEDIA_ROOT.G

Heroku
======

At first you have to create an heroku account and install the heroku_ command line app.

Then creeate your app with the heroku client and make your newly created app the default app,
to avoid having to specify it for every heroku toolbelt call with "-a":

.. code-block:: shell

    heroku create --buildpack https://github.com/heroku/heroku-buildpack-python --region eu
    heroku git:remote -a <name-of-the-app>

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

MEDIA_ROOT in S3 wont work at the moment. I used a fork of django-imagekit where I
fixed an issue with S3 and always used my fork and forgot to create a pull request
for django-imagekit_. I didn't manage to get my fork installed on heroku_ because
django-cast requires django-imagekit so even if I put it in requirements/base.txt
it get's overwritten. Bad karma from not creating a PR in time is bad.

Docker
======

to be done

.. _`virtualenvwrapper`: https://virtualenvwrapper.readthedocs.io/en/latest/
.. _`cookiecutter-django`: https://github.com/pydanny/cookiecutter-django
.. _`cookiecutter`: https://cookiecutter.readthedocs.io/en/latest/
.. _`heroku`: https://devcenter.heroku.com/articles/getting-started-with-python
.. _`mailgun`: https://mailgun.com
.. _`django-imagekit`: https://github.com/matthewwithanm/django-imagekit
