from django.conf.urls import url
from django.urls import include, path

from . import feeds
from .dashboard_views import DashboardView


app_name = "cast"
urlpatterns = [
    # API
    url(r"^api/", include("cast.api.urls", namespace="api")),
    # Dashboard
    url(r"^dashboard/", view=DashboardView.as_view(), name="dashboard"),
    # Feeds
    path(
        "<slug:slug>/feed/rss.xml",
        view=feeds.LatestEntriesFeed(),
        name="latest_entries_feed",
    ),
    path(
        "<slug:slug>/feed/podcast/<audio_format>/rss.xml",
        view=feeds.RssPodcastFeed(),
        name="podcast_feed_rss",
    ),
    path(
        "<slug:slug>/feed/podcast/<audio_format>/atom.xml",
        view=feeds.AtomPodcastFeed(),
        name="podcast_feed_atom",
    ),
]
