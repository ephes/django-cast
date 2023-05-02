######
Models
######


Some reference documentation about how the models work.

****
Post
****

A post is a single blog post. It's the parent of episodes, too.

Template Logic
==============

Since you can set a base directory for templates, the `get_template`
method is overridden to get the base directory from the request and
return the correct template.

To be able to render the description of a post without the base template,
there's a `_local_template_name` attribute set on the `Post` class that
can be used to override the template name. This is used for example in
the `get_description` method to render the description of the post using
the `post_body.html` template for the feed and the twitter card.

API-Fields
==========

There are some additional fields that can be fetched from the wagtail pages API:
* uuid - a unique identifier for the post
* visible_date - the date the post is visible, usually used for sorting
* comments_enabled - whether comments are enabled for this post
* body - the body stream field of the post
* html_overview - the rendered html of the overview section of the body (used in SPA themes)
* html_detail - the rendered html of the overview and detail section of the body (used in SPA themes)

*******
Episode
*******

A special kind of post that has some additional fields and logic.
