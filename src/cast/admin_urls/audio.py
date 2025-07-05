from typing import Any

from django.urls import path

from ..views import audio as views

urlpatterns: list[Any] = [
    path("audio", views.index, name="index"),
    path(r"audio/add/", views.add, name="add"),
    path("audio/edit/<int:audio_id>/", views.edit, name="edit"),
    path("audio/delete/<int:audio_id>/", views.delete, name="delete"),
    path("audio/chooser/", views.chooser, name="chooser"),
    path("audio/chooser/upload/", views.chooser_upload, name="chooser_upload"),
    path("audio/chooser/<int:audio_id>/", views.chosen, name="chosen"),
]
