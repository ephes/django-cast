from django.urls import path

from ..views import video as views


urlpatterns = [
    path("video", views.index, name="video_index"),
    path(r"video/add/", views.add, name="video_add"),
    path("video/edit/<int:video_id>/", views.edit, name="video_edit"),
    path("video/delete/<int:video_id>/", views.delete, name="video_delete"),
    path("video/chooser/", views.chooser, name="video_chooser"),
    path("video/chooser/upload/", views.chooser_upload, name="video_chooser_upload"),
    path("video/chooser/<int:video_id>/", views.chosen, name="video_chosen"),
]
