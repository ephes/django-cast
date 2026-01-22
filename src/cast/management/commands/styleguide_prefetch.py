from typing import cast

from django.core.management.base import BaseCommand, CommandError
from django.test import RequestFactory

from cast.views.styleguide import (
    _build_styleguide_data,
    _styleguide_context,
    _styleguide_default_theme,
)
from cast.models import get_template_base_dir_choices
from cast.views.htmx_helpers import HtmxHttpRequest


class Command(BaseCommand):
    help = "Prefetch styleguide demo data and build gallery renditions."

    def add_arguments(self, parser) -> None:
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

    def handle(self, *args, **options) -> None:
        theme = options.get("theme")
        available = {slug for slug, _name in get_template_base_dir_choices()}
        if theme is None:
            theme = _styleguide_default_theme()
        elif theme not in available:
            raise CommandError(f"Theme '{theme}' is not available")

        factory = RequestFactory()
        request = cast(HtmxHttpRequest, factory.get("/cast/styleguide/", HTTP_HOST="localhost:8000"))

        if options.get("with_renditions"):
            from django.conf import settings

            settings.CAST_STYLEGUIDE_GENERATE_RENDITIONS = True

        styleguide_data = _build_styleguide_data(request)
        _styleguide_context(styleguide_data, request, theme)

        self.stdout.write(self.style.SUCCESS(f"Styleguide prefetch complete for theme '{theme}'"))
