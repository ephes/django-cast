"""Test-only URLconf mounting Cast and its paged routes below a language prefix."""

from django.conf.urls.i18n import i18n_patterns
from django.urls import path

from tests.paged_feed_urls import cast_with_paged_routes, site_patterns

urlpatterns = site_patterns(*i18n_patterns(path("blogs/", cast_with_paged_routes())))
