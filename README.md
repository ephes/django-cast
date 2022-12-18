# Django Cast

[![name](https://badge.fury.io/py/django-cast.svg)](https://badge.fury.io/py/django-cast)
[![name](https://codecov.io/gh/ephes/django-cast/branch/main/graph/badge.svg)](https://codecov.io/gh/ephes/django-cast)
[![name](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/ephes/django-cast)

A blogging / podcasting package based on [Django](https://www.djangoproject.com/)
and [Wagtail](https://wagtail.org).

After switching to Wagtail, the documentation has to be updated. Stay tuned 😄.

**Current version: [0.2](https://django-cast.readthedocs.io/en/develop/)**

## Key Features
- Sharp responsive images via [wagtail-srcset](https://github.com/ephes/wagtail_srcset)
- Wagtail as CMS makes it possible to let non-technical people manage the content
  (blogposts, podcast episodes, ...)
- Podcast support: this packages powers [python-podcast.de](https://python-podcast.de/show)
  since 2018 using the [Podlove Web Player](https://podlove.org/podlove-web-player/)
- Video support - not as sophisticated as image / audio support, but it works 🤗
- Comments via [django-fluent-comments](https://github.com/django-fluent/django-fluent-comments)
  and a build in moderating spam filter
- Full-text search via [django-watson](https://github.com/etianen/django-watson)

## Deployment

See [the deployment documentation](https://django-cast.readthedocs.io/en/develop/installation.html).

## Roadmap

Although switching to Wagtail was a big step, there is still a lot to do. Things that are on the roadmap:

- Improve the documentation
- Code blocks for the Wagtail page editor
- Design improvements for the default theme (it's still bootstrap 4 atm)
- Make spam filter threshold configurable
- Update the [Podlove Web Player](https://podlove.org/podlove-web-player/) version

## Contributing

If you'd like to contribute, please read
[our contributing docs](https://django-cast.readthedocs.io/en/develop/contributing.html).
