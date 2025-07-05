from typing import Any

from django.urls import path

from ..views import video as views

urlpatterns: list[Any] = [
    path("video", views.index, name="index"),
    path(r"video/add/", views.add, name="add"),
    path("video/edit/<int:video_id>/", views.edit, name="edit"),
    path("video/delete/<int:video_id>/", views.delete, name="delete"),
    path("video/chooser/", views.chooser, name="chooser"),
    path("video/chooser/upload/", views.chooser_upload, name="chooser_upload"),
    path("video/chooser/<int:video_id>/", views.chosen, name="chosen"),
]
