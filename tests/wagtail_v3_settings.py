"""Disposable settings for the Wagtail 8 v3 compatibility experiment."""

from .settings import *  # noqa: F403

INSTALLED_APPS = [
    # This must run before Wagtail imports the v3 registry and freezes its schemas.
    "tests.wagtail_v3_app.apps.WagtailV3ExperimentConfig",
    *INSTALLED_APPS,  # noqa: F405
    "wagtail.api.v3",
]
ROOT_URLCONF = "tests.wagtail_v3_urls"
