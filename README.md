# Django Cast

[![name](https://img.shields.io/badge/python-3.11%7C3.12%7C3.13%7C3.14-brightgreen)](https://img.shields.io/badge/python-3.11%7C3.12%7C3.13%7C3.14-brightgreen)
[![name](https://img.shields.io/badge/django-4.2%7C5.2%7C6.0-brightgreen)](https://img.shields.io/badge/django-4.2%7C5.2%7C6.0-brightgreen)
[![name](https://img.shields.io/badge/wagtail-6%7C7-brightgreen)](https://img.shields.io/badge/wagtail-6%7C7-brightgreen)
[![name](https://badge.fury.io/py/django-cast.svg)](https://badge.fury.io/py/django-cast)
[![name](https://codecov.io/gh/ephes/django-cast/branch/develop/graph/badge.svg)](https://codecov.io/gh/ephes/django-cast)
[![name](https://img.shields.io/badge/linting-ruff-D7A023.svg)](https://github.com/astral-sh/ruff)
[![Published on Django Packages](https://img.shields.io/badge/Published%20on-Django%20Packages-0c3c26)](https://djangopackages.org/packages/p/django-cast/)

A blogging/podcasting package based on [Django](https://www.djangoproject.com/)
and [Wagtail](https://wagtail.org).

**Documentation: [django-cast.readthedocs.io](https://django-cast.readthedocs.io/en/develop/)**

## Getting Started

- New project: install `django-cast`, then use the
  [quickstart installation guide](https://django-cast.readthedocs.io/en/develop/installation.html#new-project-setup)
  and run `uv run django-cast-quickstart mysite`
- Existing Django project: follow the
  [integration installation guide](https://django-cast.readthedocs.io/en/develop/installation.html#integrating-into-existing-projects)
- Local development on django-cast itself: see the
  [development guide](https://django-cast.readthedocs.io/en/develop/development.html)

## Key Features
- [Responsive images](https://django-cast.readthedocs.io/en/develop/media/images-and-galleries.html)
- Wagtail as CMS makes it possible for non-technical people to manage the content
  (blog posts, podcast episodes, ...)
- Podcast support: this package powers [python-podcast.de](https://python-podcast.de/show)
  since 2018 using the [Podlove Web Player](https://podlove.org/podlove-web-player/)
- Video support - not as sophisticated as image / audio support, but it works 🤗
- Comments via ``django-contrib-comments`` with a built-in moderating spam filter
- Code blocks for the Wagtail page editor
- Use [Twitter Player Card](https://developer.twitter.com/en/docs/twitter-for-websites/cards/overview/player-card)
  for links to podcast episode detail pages
- Tags and categories for posts which are then included in the faceted navigation UI (beta feature)
- [Frontend themes](https://django-cast.readthedocs.io/en/develop/features/themes.html) to
  customize the look and feel of your site

## Deployment

See [the deployment documentation](https://django-cast.readthedocs.io/en/develop/operations/deployment.html).

## Upgrade note (0.2.54)

Repository alias names were removed in a breaking cleanup. Use canonical names only.

- `QuerysetData` -> `PostQuerySnapshot`
- `PostDetailRepository` -> `PostDetailContext`
- `BlogIndexRepository` -> `BlogIndexContext`
- `FeedRepository` -> `FeedContext`
- `EpisodeFeedRepository` -> `EpisodeFeedContext`
- `audio_to_dict` -> `serialize_audio`
- `video_to_dict` -> `serialize_video`
- `image_to_dict` -> `serialize_image`
- `blog_to_dict` -> `serialize_blog`
- `blog_from_data` -> `deserialize_blog`
- `post_to_dict` -> `serialize_post`
- `episode_to_dict` -> `serialize_episode`
- `transcript_to_dict` -> `serialize_transcript`

## Roadmap

- Design improvements for the default theme
- Collaborators for podcast episodes

## Contributing

If you'd like to contribute, please read
[our contributing docs](https://django-cast.readthedocs.io/en/develop/contributing.html).
