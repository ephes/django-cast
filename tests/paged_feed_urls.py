"""Test-only URLconfs for internal paged feed adapters.

Public paged routes ship together with response caching in a later step, so
``cast.urls`` does not contain them yet. These URLconfs mount the internal
adapter under the planned URL names like the consumer sites do: below
``/blogs/`` (homepage), at the root (python-podcast) and below a language prefix.
"""

from django.urls import include, path
from wagtail import urls as wagtail_urls

from cast import urls as cast_urls
from cast.paged_feeds import PAGED_FEED_URL_NAMES, internal_paged_feed_response

PAGED_ROUTES = {
    ("blog", "rss"): "<slug:slug>/feed/paged/rss.xml",
    ("blog", "atom"): "<slug:slug>/feed/paged/atom.xml",
    ("podcast", "rss"): "<slug:slug>/feed/podcast/<audio_format>/paged/rss.xml",
    ("podcast", "atom"): "<slug:slug>/feed/podcast/<audio_format>/paged/atom.xml",
}


def cast_with_paged_routes():
    paged = [
        path(
            route,
            internal_paged_feed_response,
            {"kind": kind, "representation": representation},
            name=PAGED_FEED_URL_NAMES[(kind, representation)],
        )
        for (kind, representation), route in PAGED_ROUTES.items()
    ]
    return include((cast_urls.urlpatterns + paged, "cast"), namespace="cast")


def site_patterns(*cast_mount):
    return [
        *cast_mount,
        path("posts/comments/", include("cast.comments.urls")),
        path("", include(wagtail_urls)),
    ]


urlpatterns = site_patterns(path("blogs/", cast_with_paged_routes()))
