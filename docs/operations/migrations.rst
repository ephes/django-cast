.. _migrations_overview:

********************
Database Migrations
********************

Django Cast uses Django's migration system for most database changes. However, some complex changes require special handling, particularly when working with Wagtail's page tree structure.

Standard Migrations
===================

Creating Migrations
-------------------

For most model changes:

.. code-block:: bash

    # After modifying models
    uv run manage.py makemigrations

    # Review the generated migration
    uv run manage.py showmigrations

    # Apply the migration
    uv run manage.py migrate

Migration Best Practices
------------------------

1. **Review Generated Migrations**: Always check the generated SQL
2. **Test Locally First**: Run migrations on a copy of production data
3. **Backup Before Migrating**: Always backup production before migrations
4. **Use Atomic Transactions**: Ensure migrations can be rolled back
5. **Document Complex Changes**: Add comments for non-obvious migrations

Complex Page Migrations
=======================

Migration with Restore from Backup
----------------------------------

Sometimes it's not possible to do database changes via a Django migration.
For example if you try to split up a model inheriting from Wagtails page
model, it's not possible to add / remove pages via a Django Migration
because you don't have access to the Page model in a migration
(only the database).

Atm the best option for me is to copy the production database locally,
do the migration in a notebook and then backup the migrated database and
restore it in production. A manual migration is only needed for a database
where there are models which should be added to the new model.

Steps
~~~~~

#. Backup old production database
	#. Fetch production database and restore it to the local development database
	#. Set site to localhost in wagtailadmin
#. Migrate the database structure
	#. Add a new model inheriting from the old one and prefix the attributes you want to keep with `new_`
	#. Create a new migration
	#. Use `uv pip install -e .` to install the `django-cast <https://github.com/ephes/django-cast>`_. package in the venv of your application
	#. Migrate
#. Migrate the database data manually
	#. Use a jupyter notebook to copy the old models over to the new model [blog_to_podcast_example]_
	#. Make sure to prefix uniqe page fields like `slug` with `new` first and rename it afterwards
	#. Remove the moved attributes from the old model
	#. Rename the attributes prefixed with `new_` in the new model
#. Dump local database and restore to production
	#. Change site back to `python-podcast.staging.wersdoerfer.de` with port `443`
	#. `pg_dump python_podcast | gzip > backups/db.staging.psql.gz`
	#. `cd deploy && ansible-playbook restore_database.yml --limit staging`


.. [blog_to_podcast_example] blog_to_podcast example

    .. code-block:: python

        def blog_to_podcast(blog, content_type):
            exclude = {"id", "page_ptr_id", "page_ptr", "translation_key"}
            kwargs = {
                f.name: getattr(blog, f.name)
                for f in Blog._meta.fields
                if f.name not in exclude
            }
            kwargs["slug"] = f"new_{blog.slug}"
            kwargs["content_type"] = content_type
            kwargs["new_itunes_artwork"] = blog.itunes_artwork
            kwargs["new_itunes_categories"] = blog.itunes_categories
            kwargs["new_keywords"] = blog.keywords
            kwargs["new_explicit"] = blog.explicit
            return Podcast(**kwargs)

        # first migration to add podcast model
        from django.core.management import call_command
        call_command("migrate")

        # get the original blog + parent
        original_slug = "show"
        blog = Blog.objects.get(slug=original_slug)
        blog_parent = Page.objects.parent_of(blog).first()

        # fix hostname and port
        site = Site.objects.first()
        site.hostname = "localhost"
        site.port = 8000
        site.save()

        # create new page
        podcast_content_type = ContentType.objects.get(app_label="cast", model="podcast")
        podcast = blog_to_podcast(blog, podcast_content_type)
        podcast = blog_parent.add_child(instance=podcast)

        # fix treebeard, dunno why this is needed
        from django.core.management import call_command
        call_command("fixtree")
        podcast = Podcast.objects.get(slug=f"new_{origninal_slug}")  # super important!

        # move children - this is extremely brittle!
        from wagtail.actions.move_page import MovePageAction
        for child in blog.get_children():
            mpa = MovePageAction(child, podcast, pos="last-child")
            mpa.execute()

        # delete old page
        blog.delete()

        # restore slug
        podcast.slug = original_slug
        podcast.save()

Common Migration Scenarios
==========================

Adding Fields
-------------

Simple field addition:

.. code-block:: python

    # In models.py
    class Post(Page):
        subtitle = models.CharField(max_length=255, blank=True)

Data Migrations
---------------

Creating a data migration:

.. code-block:: bash

    uv run manage.py makemigrations --empty myapp

Then edit the migration:

.. code-block:: python

    from django.db import migrations

    def populate_subtitle(apps, schema_editor):
        Post = apps.get_model('cast', 'Post')
        for post in Post.objects.all():
            post.subtitle = f"Subtitle for {post.title}"
            post.save()

    class Migration(migrations.Migration):
        dependencies = [
            ('cast', '0001_initial'),
        ]

        operations = [
            migrations.RunPython(populate_subtitle),
        ]

Troubleshooting Migrations
==========================

Common Issues
-------------

1. **Circular Dependencies**
   
   - Review migration dependencies
   - Consider squashing migrations
   - Use `--run-syncdb` for fresh installs

2. **Page Tree Corruption**
   
   - Run `manage.py fixtree`
   - Check for orphaned pages
   - Verify path and depth fields

3. **Failed Migrations**
   
   - Check migration state: `showmigrations`
   - Fake migrations if needed: `migrate --fake`
   - Restore from backup if necessary

4. **Performance Issues**
   
   - Add database indexes
   - Use `RunSQL` for complex operations
   - Consider batching large data migrations

Migration Tools
===============

Useful Commands
---------------

.. code-block:: bash

    # Show migration plan
    uv run manage.py showmigrations

    # Show SQL for a migration
    uv run manage.py sqlmigrate cast 0001

    # Check for migration issues
    uv run manage.py makemigrations --check

    # Squash migrations
    uv run manage.py squashmigrations cast 0001 0010

    # Fix Wagtail page tree
    uv run manage.py fixtree