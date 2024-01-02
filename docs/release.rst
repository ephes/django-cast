***************
Release Process
***************

Bump Version Number
-------------------

Change the version number in following files:

- cast/__init__.py
- docs/conf.py
- README.md

Javascript
----------

Build the Javascript (image-gallery component):

.. code-block:: shell

   $ cd javascript
   $ npx vite build
   $ cd dist/
   $ mv .vite/manifest.json manifest.json
   $ rm -r .vite
   $ rm ../../cast/static/cast/vite/*
   $ cp * ../../cast/static/cast/vite/

Create the Release on GitHub
----------------------------

1. Create a new tag on GitHub
2. Copy the release notes from the previous version and change them accordingly
3. Mark as pre-release

Test Python Versions and Merge develop into main
------------------------------------------------

Make sure all tests are passing on supported Python versions:

.. code-block:: bash

   $ tox

Merge the develop branch into the main branch:

.. code-block:: bash

   $ git checkout main
   $ git pull && git merge develop
   $ git push

Build the Release Wheels and Publish to PyPI
--------------------------------------------

Create the package:

.. code-block:: bash

   $ flit publish
