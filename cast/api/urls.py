from typing import Any

from django.urls import include, path, re_path
from rest_framework.schemas import get_schema_view

from . import views

app_name = "api"
schema_view = get_schema_view(title="Cast API")

urlpatterns: list[Any] = [
    path("schema/", schema_view),
    path("", views.api_root, name="root"),
    # video
    path("videos/", views.VideoListView.as_view(), name="video_list"),
    re_path(r"^videos/(?P<pk>\d+)/?$", views.VideoDetailView.as_view(), name="video_detail"),
    path(
        "upload_video/",
        views.VideoCreateView.as_view(),
        name="upload_video",
    ),
    # audio
    path("audios/", views.AudioListView.as_view(), name="audio_list"),
    re_path(r"^audios/(?P<pk>\d+)/?$", views.AudioDetailView.as_view(), name="audio_detail"),
    re_path(
        r"^audios/podlove/(?P<pk>\d+)/?$",
        views.AudioPodloveDetailView.as_view(),
        name="audio_podlove_detail",
    ),
    # facet counts
    path("facet_counts/", views.FacetCountListView.as_view(), name="facet-counts-list"),
    re_path(r"facet_counts/(?P<pk>\d+)/?$", views.FacetCountsDetailView.as_view(), name="facet-counts-detail"),
    # comment training data
    path("comment_training_data/", views.CommentTrainingDataView.as_view(), name="comment-training-data"),
    # themes
    path("themes/", views.ThemeListView.as_view(), name="theme-list"),
    path("update_theme/", views.UpdateThemeView.as_view(), name="theme-update"),
    # wagtail api
    path("wagtail/", include((views.wagtail_api_router.get_urlpatterns(), "api"), namespace="wagtail")),
]
