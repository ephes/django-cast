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

*******
Episode
*******

A special kind of post that has some additional fields and logic.
