#####
Howto
#####

This is mainly for me to remember how to do things 😁.

****************
Database Changes
****************

Migration with Restore from Backup
==================================

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
-----

#. Backup old production database
	#. Fetch production database and restore it to the local development database
	#. Set site to localhost in wagtailadmin
#. Migrate the database structure
	#. Add a new model inheriting from the old one and prefix the attributes you want to keep with `new_`
	#. Create a new migration
	#. Use `flit install -s` to install the `django-cast <https://github.com/ephes/django-cast>`_. package in the venv of your application
	#. Migrate
#. Migrate the database data manually
	#. Use a jupyter notebook to copy the old models over to the new model [example]_
	#. Make sure to prefix uniqe page fields like `slug` with `new` first and rename it afterwards
	#. Remove the moved attributes from the old model
	#. Rename the attributes prefixed with `new_` in the new model
#. Dump local database and restore to production
	#. Change site back to `python-podcast.staging.wersdoerfer.de` with port `443`
	#. `pg_dump python_podcast | gzip > backups/db.staging.psql.gz`
	#. `cd deploy && ansible-playbook restore_database.yml --limit staging`


.. [example] blog_to_podcast example

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
