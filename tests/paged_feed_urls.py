"""Test-only URLconfs mounting ``cast.urls`` (including its public paged routes) like the consumers.

Below ``/blogs/`` (homepage), at the root (python-podcast) and below a language prefix.
"""

from django.urls import include, path
from wagtail import urls as wagtail_urls


def cast_with_paged_routes():
    return include("cast.urls", namespace="cast")


def site_patterns(*cast_mount):
    return [
        *cast_mount,
        path("posts/comments/", include("cast.comments.urls")),
        path("", include(wagtail_urls)),
    ]


urlpatterns = site_patterns(path("blogs/", cast_with_paged_routes()))
