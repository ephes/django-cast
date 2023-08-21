*****************
Categories / Tags
*****************

This is a beta feature. It is not yet fully implemented. Since I don't
know yet if I will go with tags or categories, I added both and wait
which one sticks 😄.

Categories
==========

Categories are one way to group posts. They come with their own snippet
model so you can add them via the admin interface by clicking on one
of the categories. A blog post can have multiple categories and a category
can have multiple blog posts. If you want to add a new category, you have
to add it using the wagtail admin interface.

Categories might be the right thing if you do not have too many of
them and they rarely change.


Tags
====

Tags are another way to group posts. They come with their own link to
the `taggit` tag model. You can add tags to a blog post by using the
standard wagtail `tag` interface. A blog post can have multiple tags
and a tag can have multiple blog posts. If you want to add a new tag,
there's a text field with auto completion in the wagtail admin interface.

Tags might be the right thing if you have a lot of them and they change
often and you don't mind having to type them in the admin interface.
