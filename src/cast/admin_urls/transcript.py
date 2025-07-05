from typing import Any

from django.urls import path

from ..views import transcript as views

urlpatterns: list[Any] = [
    path("transcript", views.index, name="index"),
    path(r"transcript/add/", views.add, name="add"),
    path("transcript/edit/<int:transcript_id>/", views.edit, name="edit"),
    path("transcript/delete/<int:transcript_id>/", views.delete, name="delete"),
    path("transcript/chooser/", views.chooser, name="chooser"),
    path("transcript/chooser/upload/", views.chooser_upload, name="chooser_upload"),
    path("transcript/chooser/<int:transcript_id>/", views.chosen, name="chosen"),
]
