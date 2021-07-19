from django.urls import path, re_path

from wagtailmedia.views import media
from wagtailmedia.views import chooser

from .wagtail_views import video_index, video_add, video_edit, video_delete, video_chooser, video_chooser_upload, video_chosen


urlpatterns = [
    path("video", video_index, name="video_index"),
    path(r"video/add/", video_add, name="video_add"),
    path("edit/<int:video_id>/", video_edit, name="video_edit"),
    path("delete/<int:video_id>/", video_delete, name="video_delete"),
    path("video/chooser/", video_chooser, name="video_chooser"),
    path("video/chooser/upload/", video_chooser_upload, name="video_chooser_upload"),
    path("video/chooser/<int:video_id>/", video_chosen, name="video_chosen"),
    # dragons below
    path("", media.index, name="index"),
    re_path(r"(?P<media_type>audio|video|media)/add/$", media.add, name="add"),
    path("edit/<int:media_id>/", media.edit, name="edit"),
    path("delete/<int:media_id>/", media.delete, name="delete"),
    path("chooser/", chooser.chooser, name="chooser"),
    path("chooser/<int:media_id>/", chooser.media_chosen, name="media_chosen"),
    re_path(
        r"^(?P<media_type>audio|video)/chooser/upload/$",
        chooser.chooser_upload,
        name="chooser_upload",
    ),
    path("usage/<int:media_id>/", media.usage, name="media_usage"),
]
