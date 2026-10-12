from argparse import ArgumentParser
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.test import RequestFactory

from cast.http_types import HtmxHttpRequest
from cast.models import get_template_base_dir_choices
from cast.views.styleguide import (
    _build_styleguide_data,
    _styleguide_context,
    _styleguide_default_theme,
)

GENERATE_RENDITIONS_SETTING = "CAST_STYLEGUIDE_GENERATE_RENDITIONS"


@contextmanager
def generate_renditions(enabled: bool) -> Iterator[None]:
    """Turn rendition generation on for the enclosed block only.

    The setting is process-wide, so it is put back afterwards (or removed again
    if it was not set), also when the block raises. A caller using
    ``call_command`` in a long-running process keeps its own configuration.
    """
    if not enabled:
        yield
        return
    was_set = hasattr(settings, GENERATE_RENDITIONS_SETTING)
    previous = getattr(settings, GENERATE_RENDITIONS_SETTING, None)
    setattr(settings, GENERATE_RENDITIONS_SETTING, True)
    try:
        yield
    finally:
        if was_set:
            setattr(settings, GENERATE_RENDITIONS_SETTING, previous)
        else:
            delattr(settings, GENERATE_RENDITIONS_SETTING)


class Command(BaseCommand):
    help = "Prefetch styleguide demo data and build gallery renditions."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--theme",
            default=None,
            help="Theme slug to render for (defaults to the first available styleguide theme).",
        )
        parser.add_argument(
            "--with-renditions",
            action="store_true",
            help="Generate missing renditions while prefetching.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        theme = options.get("theme")
        available = {slug for slug, _name in get_template_base_dir_choices()}
        if theme is None:
            theme = _styleguide_default_theme()
        elif theme not in available:
            raise CommandError(f"Theme '{theme}' is not available")

        factory = RequestFactory()
        request = cast(HtmxHttpRequest, factory.get("/cast/styleguide/", HTTP_HOST="localhost:8000"))

        with generate_renditions(bool(options.get("with_renditions"))):
            styleguide_data = _build_styleguide_data(request)
            _styleguide_context(styleguide_data, request, theme)

        self.stdout.write(self.style.SUCCESS(f"Styleguide prefetch complete for theme '{theme}'"))
