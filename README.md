# Django Cast

[![name](https://badge.fury.io/py/django-cast.svg)](https://badge.fury.io/py/django-cast)
[![name](https://codecov.io/gh/ephes/django-cast/branch/develop/graph/badge.svg)](https://codecov.io/gh/ephes/django-cast)
[![name](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/ephes/django-cast)

A blogging/podcasting package based on [Django](https://www.djangoproject.com/)
and [Wagtail](https://wagtail.org).

After switching to Wagtail, the documentation has to be updated. Stay tuned 😄.

**Current version: [0.2.4](https://django-cast.readthedocs.io/en/develop/)**

## Key Features
- Responsive images via [wagtail-srcset](https://github.com/ephes/wagtail_srcset)
- Wagtail as CMS makes it possible for non-technical people to manage the content
  (blog posts, podcast episodes, ...)
- Podcast support: this package powers [python-podcast.de](https://python-podcast.de/show)
  since 2018 using the [Podlove Web Player](https://podlove.org/podlove-web-player/)
- Video support - not as sophisticated as image / audio support, but it works 🤗
- Comments via [django-fluent-comments](https://github.com/django-fluent/django-fluent-comments)
  and a built-in moderating spam filter
- Code blocks for the Wagtail page editor
- Use [Twitter Player Card](https://developer.twitter.com/en/docs/twitter-for-websites/cards/overview/player-card)
  for links to podcast episode detail pages


## Deployment

See [the deployment documentation](https://django-cast.readthedocs.io/en/develop/installation.html).

## Roadmap

Although switching to Wagtail was a big step, there is still a lot to do. Things that are on the roadmap:

- Improve the documentation
- Update the [Podlove Web Player](https://podlove.org/podlove-web-player/) version
- Design improvements for the default theme (it's still bootstrap 4 atm)
- Add tags for posts (TIL, etc.) and navigation
- Collaborators for podcast episodes
- Transcripts for podcast episodes

## Contributing

If you'd like to contribute, please read
[our contributing docs](https://django-cast.readthedocs.io/en/develop/contributing.html).
