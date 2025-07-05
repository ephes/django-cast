*****************
Running the Tests
*****************

Python
======

Start by checking out the source code of the project and switching to the development branch:

.. code-block:: bash

   $ git clone git@github.com:ephes/django-cast.git
   $ cd django-cast
   $ git checkout develop

Then, create a virtualenv and install the project dependencies:

.. code-block:: bash

   $ uv sync

Now create the test database:

.. code-block:: bash

   $ uv run manage.py migrate

The tests are then run by executing the following command:

.. code-block:: bash

   $ uv run pytest

You can measure the test coverage by running the following command:

.. code-block:: bash

   $ uv run coverage run -m pytest && uv run coverage html && open htmlcov/index.html

In order to make running tests faster, the test database is set up
to be reused and migrations are not applied. This implies that if you
have added a new Django migration to your codebase, you will need to
execute the following commands below to re-create the test database:

.. code-block:: bash

   $ rm tests/test_database.sqlite3  # delete the old test database
   $ uv run manage.py migrate  # re-create the test database

After that, you should be able to run the tests again.

Javascript
==========

.. code-block:: bash

   $ cd javascript
   $ npx vitest run
