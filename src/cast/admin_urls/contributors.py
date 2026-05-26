"""Wagtail admin URL configuration for contributor helper endpoints."""

from typing import Any

from django.urls import path

from ..views import contributors as views

urlpatterns: list[Any] = [
    path("links/", views.link_options, name="links"),
]
