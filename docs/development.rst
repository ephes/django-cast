===========
Development
===========

This guide covers everything you need to know to contribute to django-cast development.

Planning Future Work
====================

Planned work is tracked in the
`project backlog <https://github.com/ephes/django-cast/blob/develop/BACKLOG.md>`_.
Add or update backlog entries there instead of maintaining separate planned-work
lists in the README or docs.

Development Environment Setup
=============================

Prerequisites
-------------

Before you begin, ensure you have the following installed:

- Python 3.11 or higher
- Node.js 20.19 or higher (or Node.js 22.12 or higher)
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

The install command will:

- Create a virtual environment if one doesn't exist
- Install django-cast in editable mode
- Install all development dependencies

The repository intentionally does not track ``uv.lock`` because its test matrix
resolves several supported Django and Wagtail branches. After ``uv sync``, audit
the frozen local runtime resolution, including optional extras, with:

.. code-block:: console

   $ just audit-dependencies

Setting Up the JavaScript Environment
-------------------------------------

Navigate to the JavaScript directory and install dependencies:

.. code-block:: bash

   $ cd javascript
   $ npm install

Bootstrap5 Theme (Required for Example App)
-------------------------------------------

The example app uses the Bootstrap5 theme, which lives in a sibling repo.
Install it in editable mode:

.. code-block:: bash

   $ uv pip install -e ../cast-bootstrap5

If ``cast-bootstrap5`` is not available, the example app will fall back to the
built-in ``bootstrap4`` theme.

Database Setup
--------------

Create and migrate the development database:

.. code-block:: bash

   $ cd example
   $ uv run python manage.py migrate

Bootstrap demo content (recommended after a clean DB rebuild):

.. code-block:: bash

   $ uv run python scripts/bootstrap_example_data.py --reset-db

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

Or start Django + both Vite dev servers together:

.. code-block:: bash

   $ just dev

.. note::

   ``just dev`` will skip the Bootstrap5 or cast-vue Vite servers if the sibling
   repos (``../cast-bootstrap5`` or ``../cast-vue``) are missing, and the example
   app will fall back to the built-in ``bootstrap4`` theme.

For agent-friendly local workflow, you can also use:

.. code-block:: bash

   $ just dev-tmux          # create detached tmux session "cast-dev" (run again to attach)
   $ just dev-status        # quick health/status output
   $ just dev-logs django   # tail one service log
   $ just dev-logs-dir      # print current log directory
   $ just dev-open          # open http://localhost:8000

For JavaScript development with hot reloading:

.. code-block:: bash

   $ cd javascript
   $ npm run dev

For the Bootstrap5 theme assets (default theme), run its Vite dev server too:

.. code-block:: bash

   $ cd ../cast-bootstrap5/javascript
   $ npm run dev

If you have the optional ``cast-vue`` theme installed, run its Vite dev server
as well (see the cast-vue repository for details).

If you do not want to run Vite, set these environment variables to use the
prebuilt manifests instead:

.. code-block:: bash

   $ export CAST_VITE_DEV_MODE=0
   $ export CAST_BOOTSTRAP5_VITE_DEV_MODE=0
   $ export CAST_VUE_VITE_DEV_MODE=0

.. note::

   Podcast pages (Podlove player) rely on the Vite dev server during local
   development. Keep the relevant ``npm run dev`` process running while
   testing podcast list/detail pages to ensure the player loads.

Styleguide
----------

Use two different URLs during frontend verification. They serve different purposes.

.. note::

   These dev-only routes are gated by ``CAST_ENABLE_DEV_TOOLS`` (or deprecated
   ``CAST_ENABLE_STYLEGUIDE`` alias). If disabled, they return ``404``.
   The styleguide route is still available, but the long-term direction is the
   reference-site workflow (``ensure_reference_site`` + real page checks).

Component preview route:

.. code-block:: bash

   http://localhost:8000/cast/styleguide/

This renders seeded preview components for the active theme (cards, media blocks,
comments, galleries, podcast snippets). It is the fastest way to inspect visual
regressions in isolated sections.

Real list-page behavior route:

.. code-block:: bash

   http://localhost:8000/styleguide-blog/

This is a real Wagtail blog index page. Use it for end-to-end checks of:

- search query behavior (``?search=python``)
- facet selection (``?date_facets=2026-02&tag_facets=django``)
- filter + pagination/navigation interactions

.. note::

   ``/styleguide-blog/`` is created by the styleguide seeder. If it returns a
   404, create/update reference content first:

   .. code-block:: bash

      $ just ensure-reference-site

Switch styleguide theme via query param:

.. code-block:: bash

   http://localhost:8000/cast/styleguide/?theme=bootstrap4

If the requested theme does not provide styleguide templates, the view falls
back to a built-in theme and shows a warning banner.

Theme comparison and screenshots
--------------------------------

Compare themes side-by-side in the browser:

.. code-block:: bash

   http://localhost:8000/cast/theme-compare/?path=/styleguide-blog/

Use Playwright helpers for screenshots and console-error checks:

.. code-block:: bash

   $ just screenshot /styleguide-blog/ --theme bootstrap5
   $ just screenshot-all /styleguide-blog/
   $ just check-page /styleguide-blog/ --theme bootstrap5
   $ just compare-page /styleguide-blog/

If this is your first Playwright run on a machine, install browser binaries:

.. code-block:: bash

   $ uv run playwright install chromium

Asset freshness checks
----------------------

Detect stale built assets compared to source files:

.. code-block:: bash

   $ just verify-assets

In ``DEBUG`` mode, django-cast also emits system check warning ``cast.W001``
when local Vite source files are newer than the built manifest.

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

Run only the intentionally slower integration/dev-surface checks:

.. code-block:: bash

   $ just test-slow
   # or directly: uv run pytest -m slow

Run only the faster non-slow tests:

.. code-block:: bash

   $ just test-fast
   # or directly: uv run pytest -m "not slow"

For specific tests:

.. code-block:: bash

   $ just test-one tests/models/posts_test.py::TestPostModel::test_post_slug

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

The test database ``tests/test_database.sqlite3`` is reused between test runs for performance
(``--reuse-db``) and is built directly from the models rather than by applying migrations
(``--no-migrations``). Nothing updates the schema of a database that already exists, so it goes
stale whenever the models change - when you add a cast migration, switch branches, or upgrade a
dependency such as Wagtail that ships migrations of its own.

You do not have to clean that up by hand. ``tests/conftest.py`` records a fingerprint of every
installed app's migration files next to the database in
``tests/test_database.sqlite3.fingerprint``. When the fingerprint no longer matches, the database
file is deleted at the start of the run and pytest-django creates a fresh one. Recreating it takes
a few seconds, and a run where nothing changed pays only the cost of hashing the migration files.

To force a rebuild anyway - for instance after tests left unwanted rows behind - delete the file
or use pytest's own flag:

.. code-block:: bash

   $ uv run pytest --create-db

If you see widespread 404s or IntegrityErrors in tests (especially around Wagtail page URLs),
Wagtail's site-root path cache or leftover pages from an interrupted run may be to blame rather
than the schema. Recreating the database as shown above resets both.

Because the suite never applies a migration, a migration that does not apply cleanly would go
unnoticed. The ``migrations-oldest`` and ``migrations-latest`` tox environments cover that by
running the full migration graph against an empty throwaway database, once with the oldest
supported dependency combination (Django 5.2, Wagtail 7.0) and once with the newest:

.. code-block:: bash

   $ uv run tox -e migrations-oldest,migrations-latest

PostgreSQL Lock Tests (Optional Locally)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Normal ``just check`` and default tox environments use SQLite. Contributors do
not need PostgreSQL or Docker installed. Seven concurrency cases require real
PostgreSQL row locks and skip on SQLite.

CI runs those cases plus the publication-policy and editor publication-lock
modules in one dedicated ``postgres-locks`` job on a standard Ubuntu runner. GitHub Actions starts and
discards a PostgreSQL 17 service container for that job. It uses Python 3.12,
Django 6.1 and Wagtail 8, has a ten-minute timeout, and runs on pushes and pull
requests, not the weekly dependency-audit schedule. It does not repeat the full
test matrix or require a permanent database. Standard GitHub-hosted runners
are currently free for public repositories; see
`GitHub Actions billing <https://docs.github.com/en/actions/concepts/billing-and-usage>`_.

To run the same checks locally, optionally start a disposable PostgreSQL server
(or a PostgreSQL 17 Docker container) and run:

.. code-block:: bash

   $ uv run tox -e postgres

This opt-in environment installs its own PostgreSQL driver. Defaults are host
``127.0.0.1``, port ``5432``, user/password ``postgres`` and database
``cast_postgres_tests``. Override these with ``CAST_TEST_DB_HOST``,
``CAST_TEST_DB_PORT``, ``CAST_TEST_DB_USER``, ``CAST_TEST_DB_PASSWORD`` and
``CAST_TEST_DB``. Use only a disposable test database: each pytest command
recreates it, and the role must be able to create databases. Public/private
test media remain isolated under ``.tox/postgres``.

The first command runs the editor schedule-approval race together with the
publication-policy tests (including their database-access regressions); the
second runs the three v3 adapter races under their isolated settings.
Both commands load a pytest guard that fails before collection if the selected
backend is not PostgreSQL, so a SQLite fallback cannot silently skip the lock tests.

Test Media Files
~~~~~~~~~~~~~~~~

Uploads created by the suite land in a directory that belongs to a single test session.
``tests/conftest.py`` points ``MEDIA_ROOT`` and ``CAST_PRIVATE_MEDIA_ROOT`` at pytest's
per-session temporary directory, so nothing is written into the checkout and no run
deletes another run's files. Set ``CAST_TEST_MEDIA_ROOT`` and
``CAST_TEST_PRIVATE_MEDIA_ROOT`` to use fixed paths instead; every tox environment does
that to get a stable directory of its own under ``.tox``, and such a directory is wiped
at the start and end of the session because the next run reuses it.

Private ``FileField`` columns - the contributor voice-reference clip and the transcript
speakers sidecar - resolve their storage once, while the model class is created, so they
cannot follow a settings override. The fixture rebinds them to the session's private root
and restores them afterwards.

Media files are therefore no longer a reason to avoid running two test sessions at once.
The reused test database still is: two plain ``pytest`` runs share
``tests/test_database.sqlite3`` and fail with ``database is locked``. Give the second run
its own database to run both at the same time:

.. code-block:: bash

   $ CAST_TEST_DB=/tmp/cast-second-run.sqlite3 uv run pytest

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

Coverage uses the ``@vitest/coverage-v8`` provider and writes an HTML report to the
gitignored ``javascript/coverage/`` directory.

Type-check the TypeScript sources with ``tsc --noEmit``:

.. code-block:: bash

   $ just js-typecheck
   # or directly:
   $ cd javascript
   $ npm run typecheck

Vite and Vitest only strip types, so this is the only command that actually checks them.
It currently reports pre-existing errors, mostly in the test files, and is therefore not
part of CI yet; treat new errors in the code you touch as something to fix.

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
   # use a different worker count when needed
   $ just tox 4
   # or directly: uv run tox p -p 6

To test a specific environment:

.. code-block:: bash

   $ uv run tox -e py312-django52-wagtail70

Each environment keeps its own database, public media root, and private media root under ``.tox``
(see `Test Media Files`_). This isolation lets the default ``just tox`` recipe safely run six
environments concurrently without one test session deleting another's uploaded files. ``uv run tox -e migrations-oldest,migrations-latest``
checks that the migration graph applies to an empty database at both ends of the supported dependency
range, and ``uv run tox -e cleanup`` removes every test database and media root.

The ``django61`` and ``wagtail80`` environments also make deprecation warnings visible: they run
pytest with ``-W default::DeprecationWarning -W default::PendingDeprecationWarning`` (through
``PYTEST_ADDOPTS``) and set a matching ``PYTHONWARNINGS``. The newest supported Django and Wagtail
releases are where the next round of removals shows up first, and Django's
``RemovedInDjangoXXWarning`` classes are deprecation warnings, so these environments end with a
warnings summary that the rest of the matrix - and a plain ``pytest`` run - suppress through the
``filterwarnings`` list in ``pyproject.toml``. The warnings do not fail the run. Treat a new one
coming from ``src/cast`` as work to schedule before the framework release that removes the API, and
ignore third-party noise until the whole matrix is quiet enough to turn deprecations into errors.
CI runs ``py314-django61-wagtail80`` in its tox matrix job, so the same summary shows up there.

Code Quality
============

Run all quality checks (linting, type checking, and tests) in one command:

.. code-block:: bash

   $ just check

This runs ``just lint``, ``just typecheck``, and ``just test`` in sequence,
stopping on first failure.

Linting and Formatting
----------------------

Django-cast uses Ruff for code formatting and linting. The project is configured with:

- Line length: 119 characters
- Black-compatible formatting
- Import sorting (the ``I`` rules, so the ``[tool.ruff.lint.isort]`` options apply)

The lint rule selection is pinned in ``pyproject.toml`` (``[tool.ruff.lint] select``)
so the CI gate does not depend on the installed Ruff version. Pre-commit's Ruff hook
reads the same configuration, so ``just lint`` and ``pre-commit`` agree.

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

- ``python_version = "3.11"``
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
4. Run ``just check`` (linting, type checking, and tests in one command)
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
