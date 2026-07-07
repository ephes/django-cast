"""
Management command to create or update the reference site — a demo blog
and podcast with realistic content that exercises every template a theme
must provide.

Idempotent: safe to run repeatedly.  Supports ``--reset`` to start fresh
and ``--remote-media`` to pull real images/audio from production.

Works regardless of the ``CAST_ENABLE_DEV_TOOLS`` setting since it
creates *data*, not views.
"""

from argparse import ArgumentParser
from typing import Any, cast

from django.core.management.base import BaseCommand, CommandError
from django.test import RequestFactory

from cast.http_types import HtmxHttpRequest
from cast.models import Blog, Episode, Podcast, Post, get_template_base_dir_choices
from cast.views.styleguide import (
    STYLEGUIDE_BLOG_SLUG,
    STYLEGUIDE_EPISODE_SLUG,
    STYLEGUIDE_PODCAST_SLUG,
    STYLEGUIDE_POST_SLUG_PREFIX,
    _build_styleguide_data,
    _styleguide_context,
    _styleguide_default_theme,
)


class Command(BaseCommand):
    help = "Create or update the reference site with demo blog and podcast content."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--theme",
            default=None,
            help="Theme slug to render for (defaults to the first available theme).",
        )
        parser.add_argument(
            "--remote-media",
            action="store_true",
            help="Pull real images/audio from production for better-looking demos.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing reference site data and recreate from scratch.",
        )
        parser.add_argument(
            "--with-renditions",
            action="store_true",
            help="Generate missing image renditions while creating content.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        theme = options.get("theme")
        available = {slug for slug, _name in get_template_base_dir_choices()}
        if theme is None:
            theme = _styleguide_default_theme()
        elif theme not in available:
            raise CommandError(f"Theme '{theme}' is not available. Available: {', '.join(sorted(available))}")

        if options.get("reset"):
            self._reset_reference_site()
            self.stdout.write(self.style.WARNING("Reference site data deleted."))

        if options.get("remote_media"):
            from django.conf import settings

            settings.CAST_STYLEGUIDE_REMOTE_MEDIA = True  # type: ignore[misc]

        if options.get("with_renditions"):
            from django.conf import settings

            settings.CAST_STYLEGUIDE_GENERATE_RENDITIONS = True  # type: ignore[misc]

        factory = RequestFactory()
        request = cast(HtmxHttpRequest, factory.get("/cast/styleguide/", HTTP_HOST="localhost:8000"))

        styleguide_data = _build_styleguide_data(request)
        _styleguide_context(styleguide_data, request, theme)

        blog_url = styleguide_data.blog.get_url() or f"/{STYLEGUIDE_BLOG_SLUG}/"
        podcast_url = styleguide_data.podcast.get_url() or f"/{STYLEGUIDE_PODCAST_SLUG}/"
        post_count = Post.objects.filter(slug__startswith=STYLEGUIDE_POST_SLUG_PREFIX).count()

        self.stdout.write(self.style.SUCCESS(f"Reference site ready (theme: {theme})"))
        self.stdout.write(f"  Blog:    {blog_url} ({post_count} posts)")
        self.stdout.write(f"  Podcast: {podcast_url}")

    def _reset_reference_site(self) -> None:
        """Delete all reference site pages and associated data."""
        # Delete episodes first (children of podcast)
        Episode.objects.filter(slug=STYLEGUIDE_EPISODE_SLUG).delete()
        # Delete posts (children of blog)
        Post.objects.filter(slug__startswith=STYLEGUIDE_POST_SLUG_PREFIX).delete()
        # Delete blog and podcast
        Blog.objects.filter(slug=STYLEGUIDE_BLOG_SLUG).delete()
        Podcast.objects.filter(slug=STYLEGUIDE_PODCAST_SLUG).delete()
