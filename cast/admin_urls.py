from django.urls import path

from .views import audio as audio
from .views import wagtail_video as video


urlpatterns = [
    # video
    path("video", video.index, name="video_index"),
    path(r"video/add/", video.add, name="video_add"),
    path("video/edit/<int:video_id>/", video.edit, name="video_edit"),
    path("video/delete/<int:video_id>/", video.delete, name="video_delete"),
    path("video/chooser/", video.chooser, name="video_chooser"),
    path("video/chooser/upload/", video.chooser_upload, name="video_chooser_upload"),
    path("video/chooser/<int:video_id>/", video.chosen, name="video_chosen"),
    # audio
    path("audio", audio.index, name="audio_index"),
    path(r"audio/add/", audio.add, name="audio_add"),
    path("audio/edit/<int:audio_id>/", audio.edit, name="audio_edit"),
    path("audio/delete/<int:audio_id>/", audio.delete, name="audio_delete"),
    path("audio/chooser/", audio.chooser, name="audio_chooser"),
    path("audio/chooser/upload/", audio.chooser_upload, name="audio_chooser_upload"),
    path("audio/chooser/<int:audio_id>/", audio.chosen, name="audio_chosen"),
]
