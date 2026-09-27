"""Test-only URLconf mounting Cast and the internal paged adapters at the site root."""

from django.urls import path

from tests.paged_feed_urls import cast_with_paged_routes, site_patterns

urlpatterns = site_patterns(path("", cast_with_paged_routes()))
