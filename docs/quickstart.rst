##########
Quickstart
##########

Get a django-cast blog up and running in under 5 minutes!

**************
Prerequisites
**************

Before you begin, ensure you have:

- Python 3.10 or higher
- `uv <https://docs.astral.sh/uv/>`_ (recommended) or pip
- `ffmpeg <https://ffmpeg.org/download.html>`_ (optional, for video/audio processing)

******************
Create New Project
******************

The fastest way to start with django-cast is using the ``django-cast-quickstart`` command:

.. code-block:: shell

    # Create a new directory for your project
    mkdir myproject
    cd myproject

    # Create virtual environment and install django-cast
    uv venv
    uv pip install django-cast

    # Create a new django-cast project
    uv run django-cast-quickstart mysite

This command will:

1. Create a complete Django project structure
2. Configure all required settings
3. Run database migrations
4. Collect static files (including JavaScript for galleries and audio players)
5. Create a superuser account (username: ``user``, password: ``password``)
6. Start the development server
7. Open your browser to the Wagtail admin interface

.. warning::
   The default credentials (``user``/``password``) are for development only.
   Always change them before deploying to production!

***************
Command Options
***************

The quickstart command supports several options:

.. code-block:: shell

    # Default: Creates superuser with user/password
    uv run django-cast-quickstart mysite

    # Prompt for custom superuser credentials
    uv run django-cast-quickstart mysite --interactive-superuser

    # Skip superuser creation
    uv run django-cast-quickstart mysite --no-superuser

*****************
After Quickstart
*****************

Once the server is running, you can:

1. **Access the Wagtail admin** at http://localhost:8000/cms/
2. **Access the Django admin** at http://localhost:8000/admin/
3. **View your site** at http://localhost:8000/

Creating Your First Blog
========================

1. Log into the Wagtail admin
2. Navigate to **Pages** in the sidebar
3. Delete the default "Welcome" page if present
4. Click **Add child page** at the root level
5. Choose **Blog** as the page type
6. Fill in the blog details and publish

Creating Your First Post
========================

1. Navigate to your blog page in the admin
2. Click **Add child page**
3. Choose **Post** as the page type
4. Add your content using the rich text editor
5. Optionally add images, galleries, or audio/video
6. Publish your post

***********
Next Steps
***********

- Customize templates in ``mysite/templates/``
- Configure additional settings in ``mysite/settings.py``
- Set up a production database (PostgreSQL recommended)
- Configure media file storage for production
- Deploy to your hosting provider

For integrating django-cast into an existing Django project, see :doc:`integrate`.
