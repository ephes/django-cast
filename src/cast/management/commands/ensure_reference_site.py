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
from django.db import transaction
from django.test import RequestFactory, override_settings
from wagtail.models import Page, Site

from cast.http_types import HtmxHttpRequest
from cast.models import Blog, Podcast, Post, get_template_base_dir_choices
from cast.views.styleguide import (
    STYLEGUIDE_BLOG_SLUG,
    STYLEGUIDE_PODCAST_SLUG,
    STYLEGUIDE_USER_NAME,
    _build_styleguide_data,
    _prepare_styleguide_assets,
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

        overrides = {}
        if options.get("remote_media"):
            overrides["CAST_STYLEGUIDE_REMOTE_MEDIA"] = True
        if options.get("with_renditions"):
            overrides["CAST_STYLEGUIDE_GENERATE_RENDITIONS"] = True

        factory = RequestFactory()
        request = cast(HtmxHttpRequest, factory.get("/cast/styleguide/", HTTP_HOST="localhost:8000"))

        with override_settings(**overrides):
            if options.get("reset"):
                # Refuse ambiguous roots before any download or media write.
                self._reference_roots(lock=False)
            # Remote fetches and storage writes run before the page transaction, so
            # no row locks (or SQLite's write lock) are held during downloads.
            assets = _prepare_styleguide_assets()
            with transaction.atomic():
                if options.get("reset"):
                    self._reset_reference_site(self._reference_roots())
                styleguide_data = _build_styleguide_data(request, assets=assets)
                _styleguide_context(styleguide_data, request, theme)

        if options.get("reset"):
            self.stdout.write(self.style.WARNING("Reference site data replaced."))

        blog_url = styleguide_data.blog.get_url() or f"/{STYLEGUIDE_BLOG_SLUG}/"
        podcast_url = styleguide_data.podcast.get_url() or f"/{STYLEGUIDE_PODCAST_SLUG}/"
        post_count = Post.objects.descendant_of(styleguide_data.blog).count()

        self.stdout.write(self.style.SUCCESS(f"Reference site ready (theme: {theme})"))
        self.stdout.write(f"  Blog:    {blog_url} ({post_count} posts)")
        self.stdout.write(f"  Podcast: {podcast_url}")

    def _reference_roots(self, *, lock: bool = True) -> list[Page]:
        """Admit only the seed user's designated roots under the selected Site.

        ``lock=False`` is the side-effect-free pre-check; the locked call inside the
        rebuild transaction re-validates the same roots.
        """
        site = Site.objects.first()
        if site is None:
            return []
        roots = []
        for slug, model in ((STYLEGUIDE_BLOG_SLUG, Blog), (STYLEGUIDE_PODCAST_SLUG, Podcast)):
            queryset = Page.objects.child_of(site.root_page).filter(slug=slug)
            candidates = list(queryset.select_for_update() if lock else queryset)
            if not candidates:
                continue
            if (
                len(candidates) != 1
                or candidates[0].specific_class is not model
                or candidates[0].owner_id is None
                or candidates[0].owner.username != STYLEGUIDE_USER_NAME
            ):
                raise CommandError(f"Reference root ownership is ambiguous for '{slug}'; reset refused.")
            roots.append(candidates[0])
        return roots

    def _reset_reference_site(self, roots: list[Page]) -> None:
        """Delete only admitted roots; Wagtail owns their descendant deletion."""
        for root in roots:
            root.delete()
