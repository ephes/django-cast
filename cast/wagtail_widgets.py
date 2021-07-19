import json

from django.template.loader import render_to_string
from django.utils.translation import gettext_lazy as _

from wagtail.admin.widgets import AdminChooser

from .models import Video


class AdminVideoChooser(AdminChooser):
    choose_one_text = _("Choose a video item")
    choose_another_text = _("Choose another video item")
    link_to_chosen_text = _("Edit this video item")

    # def get_value_data(self, value):
    #     # FIXME why is this even necessary? Where is value coming from?
    #     print("get_value_data: ", value)
    #     if not isinstance(value, Video):
    #         value = Video.objects.get(pk=value)
    #     return {
    #         "id": value.pk,
    #         "edit_url": None,
    #         "title": value.title,
    #         "preview": None,
    #     }

    def get_value_data(self, value):
        print("get value data: ", value)
        return value

    def render_html(self, name, value, attrs):
        print("get instance and id: ", name, value, attrs)
        instance, value = self.get_instance_and_id(Video, value)
        original_field_html = super().render_html(name, value, attrs)

        print("render html value: ", value)
        # if value is None:
        #     raise Exception("foobabaz")
        return render_to_string(
            "cast/wagtail/video_chooser.html",
            {
                "widget": self,
                "original_field_html": original_field_html,
                "attrs": attrs,
                "value": value,
                "video": instance,
            },
        )

    def render_js_init(self, id_, name, value):
        return "createVideoChooser({0});".format(json.dumps(id_))

    class Media:
        js = [
            "js/cast/wagtail/video-chooser-modal.js",
            "js/cast/wagtail/video-chooser.js",
        ]
