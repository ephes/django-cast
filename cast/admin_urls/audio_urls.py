from django.urls import path

from ..views import audio as audio


urlpatterns = [
    path("audio", audio.index, name="index"),
    path(r"audio/add/", audio.add, name="add"),
    path("audio/edit/<int:audio_id>/", audio.edit, name="edit"),
    path("audio/delete/<int:audio_id>/", audio.delete, name="delete"),
    path("audio/chooser/", audio.chooser, name="chooser"),
    path("audio/chooser/upload/", audio.chooser_upload, name="chooser_upload"),
    path("audio/chooser/<int:audio_id>/", audio.chosen, name="chosen"),
]
