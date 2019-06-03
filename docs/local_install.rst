Locally / Setting up your development machine
=============================================

Install virtualenvwrapper_ and create a virtual environment for your project:

.. code-block:: shell

    mkvirtualenv -p /usr/local/bin/python3 foobar

Install cookiecutter_ into your newly create virtual environment:

.. code-block:: shell

    pip install cookiecutter

Use the cookiecutter-django_ template to bootstrap your project:

.. code-block:: shell

    cookiecutter https://github.com/pydanny/cookiecutter-django

Don't forget to activate the options for Docker or Heroku if you plan to use them. And
set the "use whitenoise" configutation option to "yes" because this will get your static
file serving on heroku_ work without any additional config. Saying "no" to this, will
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

Your development server should now be reachable at http://localhost:8000

Open only works on mac OS, but you can just point your browser to this url. You should be able
to sign in with your superuser account in the django admin. If you want to sign in regularily,
you have to paste the confirmation url shown on the dev-server console when you try to sign in.

Installation using Docker
-------------------------

Install:

* Docker for your OS
* docker-compose

You need to have set the docker option to "yes" when you created the project diretory.

.. code-block:: shell

    docker-compose -f local.yml build
    docker-compose -f local.yml run django ./manage.py migrate
    docker-compose -f local.yml up

Your development server should now also be reachable at http://localhost:8000

.. _`virtualenvwrapper`: https://virtualenvwrapper.readthedocs.io/en/latest/
.. _`cookiecutter-django`: https://github.com/pydanny/cookiecutter-django
.. _`cookiecutter`: https://cookiecutter.readthedocs.io/en/latest/
.. _`heroku`: https://devcenter.heroku.com/articles/getting-started-with-python
