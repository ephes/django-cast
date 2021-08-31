Analytics
*********

There only very limited analytics support here. But it's possible to import your
webservers access.log.

Immport your webserver logfile
==============================

Depends on the format of your logfile. The only supported format at the moment is
caddy.

Create a virtualenv on your production server
---------------------------------------------

At first, create a analytics user via the django admin interface. I gave
it the username 'analytics' for convenience. Then create a python virtualenv
to run the collect analytics cronjob. It will read the caddy access.log and
write the requests into to your django-cast Requests model via a rest-API.
You'll also need pandas in this environment, because the cleanup of request
is done in pandas.

.. code-block:: shell

    apt install virtualenvwrapper  # if you don't already have this installed
    apt install libpq-dev  # maybe you'll need that for psycopg2 compilation..
    mkvirtualenv -p /usr/bin/python3 your_app_name
    pip install pandas

Create a local file with all the required environment variables you need to run
django management commands locally - I named it '.analytics_env':

.. code-block:: shell

    USE_DOCKER=no
    DJANGO_AWS_ACCESS_KEY_ID=
    DJANGO_AWS_SECRET_ACCESS_KEY=
    DJANGO_AWS_STORAGE_BUCKET_NAME=
    DJANGO_SETTINGS_MODULE=config.settings.local
    USERNAME=analytics
    OBTAIN_TOKEN_URL=https://your_domain_name.com/api/api-token-auth/


Be sure that you are now able to run django management commands:

.. code-block:: shell

    env $(cat .analytics_env | xargs) ./manage.py


Get the api token for your analytics user
-----------------------------------------

If you provide the right password for your analytics user, you should now
be able to retrieve the api token for that user.

.. code-block:: shell

    env $(cat .analytics_env | xargs) ./manage.py get_api_token

Don't forget to add the api token to your '.analytics_env':

.. code-block:: shell

    API_TOKEN=d387ca7e5d2bf4932f1e9e9c9c4caec808571b39

You'll need to add two additional environment variables to your '.analytics_env':

.. code-block:: shell

    REQUEST_API_URL=https://your_domain_name.com/api/request/
    ACCESS_LOG_PATH=/var/log/caddy/your_domain_name.access.log


Set up a cronjob to run every hour or so to import your logfile
---------------------------------------------------------------

At first, place a shell script named 'analytics_cron.sh' in your project dir that you want to
execute as a cronjob. It might look like this:

.. code-block:: shell

    #!/bin/bash

    cd $HOME/your_project_dir
    (env $(cat .analytics_env | xargs) $HOME/.virtualenvs/your_env_name/bin/python manage.py access_log_import 2>&1) > access_log_import.log


Make this script executable:

.. code-block:: shell

    chmod +x analytics_cron.sh


And finally create a cronjob running every hour or something like this:

.. code-block:: shell

    crontab -e
    0 * * * * cd $HOME/your_project_dir && ./analytics_cron.sh
