from django.template.loader import render_to_string

from wagtail.images.widgets import AdminImageChooser


class AdminVideoChooser(AdminImageChooser):
    def render_html(self, name, value_data, attrs):
        value_data = value_data or {}
        original_field_html = super().render_html(name, value_data.get("id"), attrs)
        print("original_field: ", original_field_html)

        return render_to_string(
            "cast/widgets/video_chooser.html",
            {
                "widget": self,
                # "original_field_html": original_field_html,
                "attrs": attrs,
                "value": bool(
                    value_data
                ),  # only used by chooser.html to identify blank values
                "title": value_data.get("title", ""),
                "preview": value_data.get("preview", {}),
                "edit_url": value_data.get("edit_url", ""),
            },
        )
