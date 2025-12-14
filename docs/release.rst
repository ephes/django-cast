***************
Release Process
***************

Bump Version Number
-------------------

Change the version number in following files:

- cast/__init__.py
- docs/conf.py
- pyproject.toml
- README.md

Javascript
----------
Update dependencies:

.. code-block:: shell

   $ cd javascript
   $ npm outdated
   $ npm update

Build the Javascript (image-gallery component):

.. code-block:: shell

   $ just js-build-vite
   # or directly:
   $ cd javascript
   $ npx vite build
   $ cd dist/
   $ mv .vite/manifest.json manifest.json
   $ rm -r .vite
   $ rm ../../src/cast/static/cast/vite/*
   $ cp * ../../src/cast/static/cast/vite/

Build shipped legacy JavaScript (comments):

.. code-block:: shell

   $ just js-build-comments
   # or directly:
   $ cd javascript
   $ npm run build:comments

To build everything in one go:

.. code-block:: shell

   $ just js-build-all


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

Create the Release on GitHub
----------------------------

1. Create a new tag on GitHub
2. Copy the release notes from the previous version and change them accordingly
3. Mark as pre-release

Build the Release Wheels and Publish to PyPI
--------------------------------------------

Create the package:

.. code-block:: bash

   $ uv build
   $ uv publish --token your-token
