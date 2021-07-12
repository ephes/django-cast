import json

from django.template.loader import render_to_string
from django.utils.translation import gettext_lazy as _

from wagtail.admin.widgets import AdminChooser

from .models import Video


class AdminVideoChooser(AdminChooser):
    choose_one_text = _("Choose a video item")
    choose_another_text = _("Choose another video item")
    link_to_chosen_text = _("Edit this video item")

    def render_html(self, name, value, attrs):
        instance, value = self.get_instance_and_id(Video, value)
        original_field_html = super().render_html(name, value, attrs)

        return render_to_string(
            "cast/widgets/video_chooser.html",
            {
                "widget": self,
                "original_field_html": original_field_html,
                "attrs": attrs,
                "value": value,
                "video": instance,
            },
        )

    def render_js_init(self, id_, name, value):
        return "createMediaChooser({0});".format(json.dumps(id_))

    class Media:
        js = [
            "wagtailmedia/js/media-chooser-modal.js",
            "wagtailmedia/js/media-chooser.js",
        ]
