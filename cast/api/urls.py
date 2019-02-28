from django.conf.urls import url

from rest_framework.schemas import get_schema_view

from . import views

app_name = "api"
schema_view = get_schema_view(title="Cast API")

urlpatterns = [
    url(r"^schema/$", schema_view),
    url(r"^$", views.api_root, name="root"),
    # image
    url(r"^images/?$", views.ImageListView.as_view(), name="image_list"),
    url(
        r"^images/(?P<pk>\d+)/?$", views.ImageDetailView.as_view(), name="image_detail"
    ),
    url(
        regex=r"^upload_image/$",
        view=views.ImageCreateView.as_view(),
        name="upload_image",
    ),
    # gallery
    url(r"^gallery/?$", views.GalleryListView.as_view(), name="gallery_list"),
    url(
        r"^gallery/(?P<pk>\d+)/?$",
        views.GalleryDetailView.as_view(),
        name="gallery_detail",
    ),
    # video
    url(r"^videos/?$", views.VideoListView.as_view(), name="video_list"),
    url(
        r"^videos/(?P<pk>\d+)/?$", views.VideoDetailView.as_view(), name="video_detail"
    ),
    url(
        regex=r"^upload_video/$",
        view=views.VideoCreateView.as_view(),
        name="upload_video",
    ),
    # audio
    url(r"^audio/?$", views.AudioListView.as_view(), name="audio_list"),
    url(
        r"^audios/(?P<pk>\d+)/?$", views.AudioDetailView.as_view(), name="audio_detail"
    ),
    url(
        r"^audios/podlove/(?P<pk>\d+)/?$",
        views.AudioPodloveDetailView.as_view(),
        name="audio_podlove_detail",
    ),
]
