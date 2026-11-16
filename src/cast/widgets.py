"""Wagtail chooser widgets and telepath adapters for Audio and Video.

Provides ``AdminVideoChooser`` and ``AdminAudioChooser`` widgets used in
Wagtail's StreamField editor to let editors select media items via a
modal dialog. Each widget has a corresponding ``BaseChooserAdapter``
subclass that registers it with Wagtail's telepath framework for
client-side rendering.
"""

import json

from django import forms
from django.urls import reverse
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from wagtail.admin.staticfiles import versioned_static
from wagtail.admin.widgets import BaseChooser, BaseChooserAdapter

try:
    from wagtail.admin.telepath import register
except ImportError:  # pragma: no cover - Wagtail 7.0 fallback, removed in Wagtail 8
    from wagtail.telepath import register

from .models import Audio, Video


class CastChooser(BaseChooser):
    """Base chooser widget for cast media types (Audio, Video)."""

    chooser_namespace = "castvideo"
    template_name = "cast/video/chooser.html"

    @property
    def chooser_modal_url_name(self) -> str:
        return f"{self.chooser_namespace}:chooser"

    def get_chooser_modal_url(self) -> str:
        return reverse(self.chooser_modal_url_name)


class AdminVideoChooser(CastChooser):
    """Chooser widget for selecting a Video in the Wagtail admin editor."""

    choose_one_text = _("Choose a video item")
    choose_another_text = _("Choose another video item")
    link_to_chosen_text = _("Edit this video item")

    def get_value_data(self, value: Video | int | None) -> dict | None:
        if value is None:
            return value
        if not isinstance(value, Video):
            try:
                value = Video.objects.get(pk=value)
            except Video.DoesNotExist:
                return None
        assert isinstance(value, Video)
        return {
            "id": value.pk,
            "title": value.title,
            "edit_url": reverse("castvideo:edit", args=[value.id]),
        }

    def render_js_init(self, id_: str, name: str, value: dict | None) -> str:
        return f"createVideoChooser({json.dumps(id_)});"

    class Media:
        js = [
            "cast/js/wagtail/video-chooser-modal.js",
            "cast/js/wagtail/video-chooser.js",
        ]


class VideoChooserAdapter(BaseChooserAdapter):
    """Telepath adapter that registers ``AdminVideoChooser`` for client-side rendering."""

    js_constructor = "cast.wagtail.VideoChooser"

    def js_args(self, widget: AdminVideoChooser) -> list:
        return [
            widget.render_html("__NAME__", None, attrs={"id": "__ID__"}),
            widget.id_for_label("__ID__"),
        ]

    @cached_property
    def media(self) -> forms.Media:
        return forms.Media(
            js=[
                versioned_static("cast/js/wagtail/video-chooser-telepath.js"),
            ]
        )


register(VideoChooserAdapter(), AdminVideoChooser)


class AdminAudioChooser(CastChooser):
    """Chooser widget for selecting an Audio in the Wagtail admin editor."""

    choose_one_text = _("Choose an audio item")
    choose_another_text = _("Choose another audio item")
    link_to_chosen_text = _("Edit this audio item")
    chooser_namespace = "castaudio"
    template_name = "cast/audio/chooser.html"

    def get_value_data(self, value: Audio | int | None) -> dict | None:
        if value is None:
            return value
        if not isinstance(value, Audio):
            try:
                value = Audio.objects.get(pk=value)
            except Audio.DoesNotExist:
                return None
        assert isinstance(value, Audio)
        return {
            "id": value.pk,
            "title": value.title,
            "edit_url": reverse("castaudio:edit", args=[value.id]),
        }

    def render_js_init(self, id_: str, name: str, value: dict | None) -> str:
        return f"createAudioChooser({json.dumps(id_)});"

    class Media:
        js = [
            "cast/js/wagtail/audio-chooser-modal.js",
            "cast/js/wagtail/audio-chooser.js",
        ]


class AudioChooserAdapter(BaseChooserAdapter):
    """Telepath adapter that registers ``AdminAudioChooser`` for client-side rendering."""

    js_constructor = "cast.wagtail.AudioChooser"

    def js_args(self, widget: AdminAudioChooser) -> list:
        return [
            widget.render_html("__NAME__", None, attrs={"id": "__ID__"}),
            widget.id_for_label("__ID__"),
        ]

    @cached_property
    def media(self) -> forms.Media:
        return forms.Media(
            js=[
                versioned_static("cast/js/wagtail/audio-chooser-telepath.js"),
            ]
        )


register(AudioChooserAdapter(), AdminAudioChooser)
