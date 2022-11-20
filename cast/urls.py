from django.urls import include, path
from django.views.decorators.cache import cache_page

from . import feeds
from .views.dashboard import DashboardView

app_name = "cast"
urlpatterns = [
    # API
    # url(r"^api/", include("cast.api.urls", namespace="api")),
    path("api/", include("cast.api.urls", namespace="api")),
    # Dashboard
    path("dashboard/", view=DashboardView.as_view(), name="dashboard"),
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
]
