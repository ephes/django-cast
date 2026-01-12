===========
Development
===========

This guide covers everything you need to know to contribute to django-cast development.

Development Environment Setup
=============================

Prerequisites
-------------

Before you begin, ensure you have the following installed:

- Python 3.11 or higher
- Node.js 18 or higher
- `uv <https://github.com/astral-sh/uv>`_ for Python package management
- `just <https://github.com/casey/just>`_ command runner
- Git

Cloning the Repository
----------------------

Start by forking and cloning the django-cast repository:

.. code-block:: bash

   $ git clone git@github.com:your-username/django-cast.git
   $ cd django-cast
   $ git checkout develop

.. note::

   Development happens on the ``develop`` branch. The ``main`` branch is reserved for stable releases.

Setting Up the Python Environment
---------------------------------

Create a virtual environment and install all dependencies:

.. code-block:: bash

   $ just install
   # or directly: uv sync

This command will:

- Create a virtual environment if one doesn't exist
- Install django-cast in editable mode
- Install all development dependencies

Setting Up the JavaScript Environment
-------------------------------------

Navigate to the JavaScript directory and install dependencies:

.. code-block:: bash

   $ cd javascript
   $ npm install

Database Setup
--------------

Create and migrate the development database:

.. code-block:: bash

   $ cd example
   $ uv run python manage.py migrate

.. note::

   This repository contains two ``manage.py`` entry points:

   - ``manage.py`` (repository root) defaults to ``tests.settings`` and is mainly used for running the test suite.
   - ``example/manage.py`` uses ``example_site.settings.dev`` and is intended for interactive development.

Running the Development Server
------------------------------

Django-cast is typically developed as an installed package in a separate project.
For quick testing, you can use the example project:

.. code-block:: bash

   $ cd example
   $ uv run python manage.py runserver

For JavaScript development with hot reloading:

.. code-block:: bash

   $ cd javascript
   $ npx vite

.. note::

   Podcast pages (Podlove player) rely on the Vite dev server during local
   development. Keep ``npx vite`` running while testing podcast list/detail
   pages to ensure the player loads.

Podlove Performance Data
------------------------

To create local podcast data that exercises the Podlove player:

.. code-block:: bash

   $ cd example
   $ uv run python scripts/create_podlove_perf_data.py --episodes 5 --transcripts 200

This creates a podcast at ``/show/`` with multiple episodes and transcript
payloads to profile list and detail pages. Increase ``--transcripts`` to mimic
heavier payloads. If the slug already exists, delete the data or pick a
different ``--slug`` value.

.. note::

   The Podlove subscribe button bundle is a vendored, minified asset (upstream
   last updated in 2019). If you apply a local patch for layout stability, add a
   short header comment with the upstream URL and patch date, and record the
   change in release notes.

.. _Running Tests:

Running Tests
=============

Python Tests
------------

Run the Python test suite:

.. code-block:: bash

   $ just test
   # or directly: uv run pytest

For specific tests:

.. code-block:: bash

   $ just test-one tests/models_test.py::TestPostModel::test_post_slug

Test Coverage
~~~~~~~~~~~~~

Generate a coverage report:

.. code-block:: bash

   $ just coverage

This runs the tests with coverage and opens the HTML report in your browser.

Or manually:

.. code-block:: bash

   $ uv run coverage run -m pytest
   $ uv run coverage html
   $ open htmlcov/index.html

Test Database Management
~~~~~~~~~~~~~~~~~~~~~~~~

The test database is reused between test runs for performance. If you've added new migrations:

.. code-block:: bash

   $ rm tests/test_database.sqlite3  # Remove old test database
   $ uv run python manage.py migrate  # Recreate with new migrations (uses tests.settings)

JavaScript Tests
----------------

Run JavaScript tests with Vitest:

.. code-block:: bash

   $ just js-test
   $ just js-test-watch
   $ just js-coverage
   # or directly:
   $ cd javascript
   $ npx vitest run

Build shipped JavaScript assets:

.. code-block:: bash

   $ just js-build-comments
   # or directly:
   $ cd javascript
   $ npm run build:comments

Testing Multiple Django/Wagtail Versions
----------------------------------------

Use tox to test against multiple Django and Wagtail versions:

.. code-block:: bash

   $ just tox
   # or directly: uv run tox

To test a specific environment:

.. code-block:: bash

   $ uv run tox -e py314-django52-wagtail7

Code Quality
============

Linting and Formatting
----------------------

Django-cast uses Ruff for code formatting and linting. The project is configured with:

- Line length: 119 characters
- Black-compatible formatting
- Import sorting

Format your code:

.. code-block:: bash

   $ just lint

Fix linting issues:

.. code-block:: bash

   $ uv run ruff format .
   $ uv run ruff check --fix .

Pre-commit Hooks
----------------

Set up pre-commit hooks to automatically check code quality:

.. code-block:: bash

   $ pre-commit install

Run all hooks manually:

.. code-block:: bash

   $ just pre-commit
   # or directly: pre-commit run --all-files

The pre-commit configuration includes:

- Ruff formatting and linting
- djhtml template formatting
- Trailing whitespace removal
- End-of-file fixes
- YAML validation

Type Checking
=============

Run mypy for static type checking:

.. code-block:: bash

   $ just typecheck
   # or directly: uv run mypy

The project uses type hints throughout the codebase. When adding new code, please include appropriate type annotations.

Configuration for mypy is in ``pyproject.toml``. Key settings include:

- ``python_version = "3.14"``
- ``ignore_missing_imports = true``
- ``plugins = ["mypy_django_plugin.main"]``

Building Documentation
======================

The documentation uses Sphinx with the Furo theme.

Building Locally
----------------

Build the documentation:

.. code-block:: bash

   $ just docs

Or manually:

.. code-block:: bash

   $ make -C docs clean
   $ make -C docs html

View the built documentation:

.. code-block:: bash

   $ open docs/_build/html/index.html

Documentation Standards
-----------------------

- Use reStructuredText format for documentation files
- Include code examples where appropriate
- Document all public APIs
- Keep documentation up-to-date with code changes

Writing Documentation
---------------------

When adding new features:

1. Update relevant .rst files in the ``docs/`` directory
2. Add docstrings to new Python functions/classes
3. Include usage examples
4. Update the changelog if applicable

Package Building
================

Django-cast uses the ``uv_build`` backend (not hatchling). Configuration is in ``pyproject.toml``:

- Build backend: ``uv_build``
- Source layout: ``src/cast/``
- Module configuration: ``module-root = "src"`` and ``module-name = "cast"``

To build the package locally:

.. code-block:: bash

   $ uv build

This creates wheel and source distributions in the ``dist/`` directory.

For the complete release process, see :doc:`/release`.

Development Workflow
====================

Branch Strategy
---------------

- ``main``: Stable releases only
- ``develop``: Active development
- Feature branches: Branch from ``develop`` for new features
- Hotfix branches: Branch from ``main`` for critical fixes

Making Changes
--------------

1. Create a feature branch from ``develop``
2. Make your changes
3. Add tests for new functionality
4. Run tests and linting
5. Update documentation
6. Create a pull request to ``develop``

Pull Request Guidelines
-----------------------

- Include a clear description of changes
- Reference any related issues
- Ensure all tests pass
- Maintain or improve code coverage
- Update documentation as needed
- Follow the existing code style

Debugging Tips
==============

Django Extensions
-----------------

The example project enables ``django-extensions`` in ``example/example_site/settings/dev.py`` (e.g. ``shell_plus``).

Optional Debug Toolbar
----------------------

If you want to use Django Debug Toolbar, add it to your environment and enable it in
``example/example_site/settings/local.py`` (which is imported from ``dev.py`` if present).

Logging
-------

Enable detailed logging during development:

.. code-block:: python

   LOGGING = {
       'version': 1,
       'disable_existing_loggers': False,
       'handlers': {
           'console': {
               'class': 'logging.StreamHandler',
           },
       },
       'loggers': {
           'cast': {
               'handlers': ['console'],
               'level': 'DEBUG',
           },
       },
   }

Common Issues
=============

Import Errors
-------------

Since the project uses src layout (``src/cast/``), ensure:

- The project is installed into your environment (``just install`` / ``uv sync``)
- Imports use ``cast`` (not ``src.cast``)
- PYTHONPATH includes src directory when needed

Database Migration Conflicts
----------------------------

When working with migrations:

1. Always create migrations on the latest ``develop`` branch
2. If conflicts occur, delete and recreate migrations
3. Squash migrations periodically to keep them manageable

Getting Help
============

- Open an issue on `GitHub <https://github.com/ephes/django-cast/issues>`_
- Check existing issues and pull requests
- Review the :doc:`contributing` guide
- Ask questions in discussions

Additional Resources
====================

- :doc:`/contributing` - Contribution guidelines
- `GitHub Repository <https://github.com/ephes/django-cast>`_
- `PyPI Package <https://pypi.org/project/django-cast/>`_
- `Example Project <https://github.com/ephes/django-cast/tree/main/example>`_
