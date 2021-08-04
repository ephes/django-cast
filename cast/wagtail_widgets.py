import json

from django import forms
from django.urls import reverse
from django.template.loader import render_to_string
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _

from wagtail.core.telepath import register
from wagtail.admin.widgets import AdminChooser
from wagtail.admin.staticfiles import versioned_static
from wagtail.core.widget_adapters import WidgetAdapter

from .models import Video


class AdminVideoChooser(AdminChooser):
    choose_one_text = _("Choose a video item")
    choose_another_text = _("Choose another video item")
    link_to_chosen_text = _("Edit this video item")

    def get_value_data(self, value):
        if value is None:
            return value
        if not isinstance(value, Video):
            value = Video.objects.get(pk=value)
        return {
            "id": value.pk,
            "title": value.title,
            "edit_link": reverse("castmedia:video_edit", args=[value.id]),
        }

    def render_html(self, name, value, attrs):
        value = value if value is not None else {}
        original_field_html = super().render_html(name, value.get("id"), attrs)

        return render_to_string(
            "cast/wagtail/video_chooser.html",
            {
                "widget": self,
                "original_field_html": original_field_html,
                "attrs": attrs,
                "value": value != {},  # only used to identify blank values
                "title": value.get("title", ""),
                "edit_url": value.get("edit_url", ""),
            },
        )

    def render_js_init(self, id_, name, value):
        return "createVideoChooser({0});".format(json.dumps(id_))

    class Media:
        js = [
            "js/cast/wagtail/video-chooser-modal.js",
            "js/cast/wagtail/video-chooser.js",
        ]


class VideoChooserAdapter(WidgetAdapter):
    js_constructor = 'cast.wagtail.VideoChooser'

    def js_args(self, widget):
        return [
            widget.render_html('__NAME__', None, attrs={'id': '__ID__'}),
            widget.id_for_label('__ID__'),
        ]

    @cached_property
    def media(self):
        return forms.Media(js=[
            versioned_static('js/cast/wagtail/video-chooser-telepath.js'),
        ])


register(VideoChooserAdapter(), AdminVideoChooser)