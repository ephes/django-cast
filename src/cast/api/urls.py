from typing import Any

from django.urls import include, path, re_path

from . import views
from .editor import media as editor_media
from .editor import views as editor_views

app_name = "api"

urlpatterns: list[Any] = [
    path("", views.api_root, name="root"),
    # content editing API (editor)
    path("editor/parents/", editor_views.ParentsListView.as_view(), name="editor_parents"),
    path("editor/posts/", editor_views.PostCreateView.as_view(), name="editor_post_create"),
    path("editor/posts/<int:pk>/publish/", editor_views.PostPublishView.as_view(), name="editor_post_publish"),
    path("editor/posts/<int:pk>/", editor_views.PostDetailView.as_view(), name="editor_post_detail"),
    path("editor/episodes/", editor_views.EpisodeCreateView.as_view(), name="editor_episode_create"),
    path("editor/episodes/<int:pk>/", editor_views.EpisodeDetailView.as_view(), name="editor_episode_detail"),
    path("editor/media/images/", editor_media.EditorImageListCreateView.as_view(), name="editor_media_images"),
    path("editor/media/audios/", editor_media.EditorAudioListCreateView.as_view(), name="editor_media_audios"),
    path("editor/media/videos/", editor_media.EditorVideoListCreateView.as_view(), name="editor_media_videos"),
    path(
        "editor/media/collections/", editor_media.EditorMediaCollectionsView.as_view(), name="editor_media_collections"
    ),
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
        r"^audios/podlove/(?P<pk>\d+)/(?:post/(?P<post_id>\d+)/)?$",
        views.AudioPodloveDetailView.as_view(),
        name="audio_podlove_detail",
    ),
    re_path(
        r"^audios/(?P<pk>\d+)/player-transcript/$",
        views.AudioPlayerTranscriptView.as_view(),
        name="audio_player_transcript",
    ),
    path("audios/player_config/", views.PlayerConfig.as_view(), name="player_config"),
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
