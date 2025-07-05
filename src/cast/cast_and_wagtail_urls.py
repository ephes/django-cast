from django.urls import include, path
from wagtail import urls as wagtail_urls
from wagtail.admin import urls as wagtailadmin_urls

urlpatterns = [
    path("cast/comments/", include("fluent_comments.urls")),
    path("cast/", include("cast.urls", namespace="cast")),
    path("cms/", include(wagtailadmin_urls)),
    path("", include(wagtail_urls)),
]
