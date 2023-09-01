from typing import Any

from django.urls import include, path
from django.views.decorators.cache import cache_page

from . import feeds
from .views import meta
from .views.theme import select_theme

app_name = "cast"
urlpatterns: list[Any] = [
    # API
    path("api/", include("cast.api.urls", namespace="api")),
    # Feeds
    path(
        "<slug:slug>/feed/rss.xml",
        view=cache_page(5 * 60)(feeds.LatestEntriesFeed()),
        name="latest_entries_feed",
    ),
    path(
        "<slug:slug>/feed/podcast/<audio_format>/rss.xml",
        view=cache_page(5 * 60)(feeds.RssPodcastFeed()),
        name="podcast_feed_rss",
    ),
    path(
        "<slug:slug>/feed/podcast/<audio_format>/atom.xml",
        view=cache_page(5 * 60)(feeds.AtomPodcastFeed()),
        name="podcast_feed_atom",
    ),
    # Meta views like twitter player cards etc
    path("<slug:blog_slug>/<slug:episode_slug>/twitter-player/", view=meta.twitter_player, name="twitter-player"),
    # Store selected theme in session
    path("select-theme/", view=select_theme, name="select-theme"),
]
