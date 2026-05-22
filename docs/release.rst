***************
Release Process
***************

Bump Version Number
-------------------

Change the version number in the following files:

- ``src/cast/__init__.py``
- ``docs/conf.py``
- ``pyproject.toml``

The ``README.md`` "Upgrade note" heading is intentionally **not** bumped each
release: it stays pinned to the version that introduced the breaking change it
describes (e.g. ``Upgrade note (0.2.54)``). Replace that section only when a
newer breaking change warrants it.

Update the release notes date in ``docs/releases/<version>.rst`` from
"(unreleased)" to today's date (e.g. ``0.2.53 (2026-02-26)``).
This must happen **before** tagging the release. Verify the file is listed
in ``docs/releases/index.rst``.

Commit and push all release-prep changes on develop before proceeding.

Run Checks
----------

Make sure lint, type checking, and tests pass:

.. code-block:: bash

   $ just check

JavaScript
----------

Update dependencies and rebuild all shipped assets:

.. code-block:: shell

   $ cd javascript
   $ npm outdated
   $ npm update
   $ cd ..
   $ just js-build-all

Test Python Versions
--------------------

Make sure all tests pass on supported Python versions:

.. code-block:: bash

   $ uv run tox

Merge develop into main
-----------------------

.. code-block:: bash

   $ git checkout main
   $ git pull && git merge origin/develop
   $ git push

Create the Release on GitHub
----------------------------

Use ``gh`` to create a tagged pre-release. Use previous releases as a
template for the notes (Highlights / Improvements / Fixes / Docs sections):

.. code-block:: bash

   $ gh release create <version> --target main \
       --title "<version> (YYYY-MM-DD)" \
       --prerelease \
       --notes "$(cat <<'EOF'
   ## <version> (YYYY-MM-DD)

   ### Highlights
   - ...

   ### Improvements
   - ...

   ### Fixes
   - ...

   ### Docs / Maintenance
   - ...
   EOF
   )"

Build and Publish to PyPI
-------------------------

.. code-block:: bash

   $ uv build
   $ uv publish --token your-token

Prepare Next Development Version
---------------------------------

Switch back to develop and bump the version to the next unreleased version:

.. code-block:: bash

   $ git checkout develop

Update the version number in:

- ``pyproject.toml``
- ``docs/conf.py``
- ``src/cast/__init__.py``

Create a new release notes file ``docs/releases/<next-version>.rst`` with
"(unreleased)" as the date, and add it to ``docs/releases/index.rst``.

Commit the version bump to develop.

.. important::

   All new development work must happen on the **develop** branch.
   Never commit directly to main.
