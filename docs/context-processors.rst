******************
Context Processors
******************

=======================
Template base Directory
=======================

There are probably more pages in your site that are not a blog
or a post or otherwise related to wagtail. How do you use the same
base template for all of them? And how do you switch the base
template for those pages automatically when you switch the
base template / theme for your site in wagtail?

The answer is to use a `context processor <https://docs.djangoproject.com/en/4.1/ref/templates/api/#writing-your-own-context-processors>`_.
It will add two variables to the context of every template in your site:

- ``cast_base_template``: the base template to use for the current theme
- ``cast_site_template_base_dir``: the raw template base directory
  for the current theme holding ``bootstrap4`` or ``plain`` for example

The ``cast_base_template`` variable is the one you could use in
your local template to extend the base template:

.. code-block:: html+django

    {% extends cast_base_template %}
    ...

If you want to use this context processor, add it to your
``settings.py``:

.. code-block:: python

    TEMPLATES = [
        {
            'BACKEND': 'django.template.backends.django.DjangoTemplates',
            'DIRS': [],
            'APP_DIRS': True,
            'OPTIONS': {
                'context_processors': [
                    ...
                    'cast.context_processors.site_template_base_dir',
                ],
            },
        },
    ]
