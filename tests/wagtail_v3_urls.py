"""URL configuration that mounts Wagtail v3 only for its experiment tests."""

from django.urls import path
from wagtail.api.v3.urls import api

from .urls import urlpatterns as default_urlpatterns

urlpatterns = [path("_wagtail-v3/", api.urls), *default_urlpatterns]
