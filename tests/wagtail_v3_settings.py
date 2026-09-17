"""Disposable settings for the Wagtail 8 v3 compatibility experiment."""

from .settings import *  # noqa: F403

INSTALLED_APPS = [*INSTALLED_APPS, "wagtail.api.v3"]  # noqa: F405
ROOT_URLCONF = "tests.wagtail_v3_urls"
