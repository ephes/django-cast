import json
from typing import Union

from django import forms
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.functional import cached_property
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from wagtail.admin.staticfiles import versioned_static
from wagtail.admin.widgets import BaseChooser, BaseChooserAdapter
from wagtail.telepath import register

from .models import Audio, Video


def add_display_none_to_chooser_button(html: str) -> str:
    """
    Workaround for duplicate chooser button in wagtail admin.
    """
    return mark_safe(html.replace("data-chooser-action-choose", "data-chooser-action-choose style='display: none'"))


class CastChooser(BaseChooser):
    chooser_namespace = "castvideo"
    template_name = "cast/video/chooser.html"

    @property
    def chooser_modal_url_name(self) -> str:
        return f"{self.chooser_namespace}:chooser"

    def get_chooser_modal_url(self) -> str:
        return reverse(self.chooser_modal_url_name)

    def render_html(self, name: str, value: dict | None, attrs: dict) -> str:
        value = value if value is not None else {}
        original_field_html = super().render_html(name, value.get("id"), attrs)
        original_field_html = add_display_none_to_chooser_button(original_field_html)

        context = {
            "widget": self,
            "original_field_html": original_field_html,
            "attrs": attrs,
            "value": value != {},  # only used to identify blank values
            "title": value.get("title", ""),
            "edit_url": value.get("edit_url", ""),
        }
        html = render_to_string(self.template_name, context=context)
        return html


class AdminVideoChooser(CastChooser):
    choose_one_text = _("Choose a video item")
    choose_another_text = _("Choose another video item")
    link_to_chosen_text = _("Edit this video item")

    def get_value_data(self, value: Video | int | None) -> dict | None:
        if value is None:
            return value
        if not isinstance(value, Video):
            value = Video.objects.get(pk=value)
        assert isinstance(value, Video)
        return {
            "id": value.pk,
            "title": value.title,
            "edit_link": reverse("castvideo:edit", args=[value.id]),
        }

    def render_html(self, name: str, value: dict | None, attrs: dict) -> str:
        value = value if value is not None else {}
        original_field_html = super().render_html(name, value.get("id"), attrs)
        original_field_html = add_display_none_to_chooser_button(original_field_html)

        context = {
            "widget": self,
            "original_field_html": original_field_html,
            "attrs": attrs,
            "value": value != {},  # only used to identify blank values
            "title": value.get("title", ""),
            "edit_url": value.get("edit_url", ""),
        }
        html = render_to_string("cast/video/chooser.html", context=context)
        return html

    def render_js_init(self, id_: int, name: str, value: dict | None) -> str:
        return f"createVideoChooser({json.dumps(id_)});"

    class Media:
        js = [
            "cast/js/wagtail/video-chooser-modal.js",
            "cast/js/wagtail/video-chooser.js",
        ]


class VideoChooserAdapter(BaseChooserAdapter):
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
    choose_one_text = _("Choose an audio item")
    choose_another_text = _("Choose another audio item")
    link_to_chosen_text = _("Edit this audio item")
    chooser_namespace = "castaudio"
    template_name = "cast/audio/chooser.html"

    def get_value_data(self, value: Union["Video", int] | None) -> dict | None:
        if value is None:
            return value
        if not isinstance(value, Audio):
            value = Audio.objects.get(pk=value)
        assert isinstance(value, Audio)
        return {
            "id": value.pk,
            "title": value.title,
            "edit_link": reverse("castaudio:edit", args=[value.id]),
        }

    def render_js_init(self, id_, name: str, value: dict | None) -> str:
        return f"createAudioChooser({json.dumps(id_)});"

    class Media:
        js = [
            "cast/js/wagtail/audio-chooser-modal.js",
            "cast/js/wagtail/audio-chooser.js",
        ]


class AudioChooserAdapter(BaseChooserAdapter):
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
