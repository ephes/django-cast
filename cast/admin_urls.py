from django.urls import path

from .views import wagtail_video as video

urlpatterns = [
    path("video", video.index, name="video_index"),
    path(r"video/add/", video.add, name="video_add"),
    path("edit/<int:video_id>/", video.edit, name="video_edit"),
    path("delete/<int:video_id>/", video.delete, name="video_delete"),
    path("video/chooser/", video.chooser, name="video_chooser"),
    path("video/chooser/upload/", video.chooser_upload, name="video_chooser_upload"),
    path("video/chooser/<int:video_id>/", video.chosen, name="video_chosen"),
]
