from django.conf.urls import url, include

from . import views

app_name = "cast"
urlpatterns = [
    url(r"^api/", include("cast.api.urls", namespace="api")),
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
        regex=r"^(?P<slug>[^/]+)/feed.xml$",
        view=views.LatestEntriesFeed(),
        name="post_feed",
    ),
    url(
        regex=r"^(?P<slug>[^/]+)_detail/$",
        view=views.BlogDetailView.as_view(),
        name="blog_detail",
    ),
]
