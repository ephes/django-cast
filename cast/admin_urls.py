from django.urls import path

from .wagtail_views import video_index, video_add, video_edit, video_delete, video_chooser, video_chooser_upload, video_chosen


urlpatterns = [
    path("video", video_index, name="video_index"),
    path(r"video/add/", video_add, name="video_add"),
    path("edit/<int:video_id>/", video_edit, name="video_edit"),
    path("delete/<int:video_id>/", video_delete, name="video_delete"),
    path("video/chooser/", video_chooser, name="video_chooser"),
    path("video/chooser/upload/", video_chooser_upload, name="video_chooser_upload"),
    path("video/chooser/<int:video_id>/", video_chosen, name="video_chosen"),
]
