.. _content_organization:

********************
Content Organization
********************

Django Cast provides flexible ways to organize and categorize your content
through tags and categories. This helps readers discover related content and
improves site navigation.

*****************
Categories / Tags
*****************

Django Cast supports **both** categories and tags as content-organization
primitives, and both are enabled by default. They are not competing options you
have to choose between: they solve different problems, so you can use either,
both, or neither.

- **Categories** are best for a small, stable, curated set of groupings that
  rarely changes.
- **Tags** are best for a large, freeform set of labels that changes often.

Both power the faceted navigation on blog and podcast list pages, so readers can
narrow posts by category and by tag with live result counts. See
:ref:`search_overview` for the filter parameters and facet behavior.

Categories
==========

Categories are one way to group posts. They come with their own snippet
model so you can add them via the admin interface by clicking on one
of the categories. A blog post can have multiple categories and a category
can have multiple blog posts. If you want to add a new category, you have
to add it using the wagtail admin interface.

Categories are the right choice when you do not have too many of them and
they rarely change.


Tags
====

Tags are another way to group posts. They come with their own link to
the `taggit` tag model. You can add tags to a blog post by using the
standard wagtail `tag` interface. A blog post can have multiple tags
and a tag can have multiple blog posts. If you want to add a new tag,
there's a text field with auto completion in the wagtail admin interface.

Tags are the right choice when you have a lot of them, they change often,
and you don't mind typing them in the admin interface.
