from django.conf.urls import url
from django.urls import path, include

from . import views
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
    # Regular django views
    url(
        regex=r"^(?P<slug>[^/]+)/add/$",
        view=views.PostCreateView.as_view(),
        name="post_create",
    ),
    url(
        regex=r"^(?P<blog_slug>[^/]+)/(?P<slug>[^/]+)/update/$",
        view=views.PostUpdateView.as_view(),
        name="post_update",
    ),
    url(
        regex=r"^(?P<blog_slug>[^/]+)/(?P<slug>[^/]+)/$",
        view=views.PostDetailView.as_view(),
        name="post_detail",
    ),
    url(
        regex=r"^(?P<slug>[^/]+)/$",
        view=views.PostsListView.as_view(),
        name="post_list",
    ),
    url(
        regex=r"^(?P<slug>[^/]+)_detail/$",
        view=views.BlogDetailView.as_view(),
        name="blog_detail",
    ),
]
