"""Django app configuration for the Wagtail v3 experiment."""

from django.apps import AppConfig


class WagtailV3ExperimentConfig(AppConfig):
    """Apply test-only field configuration before Wagtail builds v3 schemas."""

    name = "tests.wagtail_v3_app"

    def ready(self) -> None:
        from tests.wagtail_v3_writable import enable_test_writes

        enable_test_writes()
