"""Wagtail admin URL configuration for Voxhelm transcript actions."""

from typing import Any

from django.urls import path

from ..views import voxhelm as views

urlpatterns: list[Any] = [
    path("episode/<int:episode_id>/generate-transcript/", views.generate_episode_transcript, name="generate_episode"),
    path("audio/<int:audio_id>/generate-transcript/", views.generate_audio_transcript, name="generate_audio"),
]
