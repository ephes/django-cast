*****************
Running the Tests
*****************

Python
======

The tests are run by executing the following command:

.. code-block:: bash

   $ pytest

In order to make running tests faster, the test database is set up
to be reused and migrations are not applied. This implies that if you
have added a new Django migration to your codebase, you will need to
execute the following commands below to re-create the test database:

.. code-block:: bash

   $ rm tests/test_database.sqlite3  # delete the old test database
   $ python manage.py migrate  # re-create the test database

After that, you should be able to run the tests again.

Javascript
==========

.. code-block:: bash

   $ cd javascript
   $ npx vittest run
