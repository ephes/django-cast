from itertools import tee, islice, chain

from django.forms.utils import flatatt
from django.utils.html import format_html
from django.utils.html import format_html_join
from django.utils.functional import cached_property

from wagtail.core.blocks import ListBlock
from wagtail.core.blocks import ChooserBlock

from wagtailmedia.blocks import AbstractMediaChooserBlock


def previous_and_next(iterable):
    prevs, items, nexts = tee(iterable, 3)
    prevs = chain([None], prevs)
    nexts = chain(islice(nexts, 1, None), [None])
    return zip(prevs, items, nexts)


class GalleryBlock(ListBlock):
    class Meta:
        template = "cast/wagtail_gallery_block.html"

    def add_prev_next(self, gallery):
        for previous_image, current_image, next_image in previous_and_next(gallery):
            current_image.prev = (
                "false" if previous_image is None else f"img-{previous_image.pk}"
            )
            current_image.next = (
                "false" if next_image is None else f"img-{next_image.pk}"
            )

    def get_context(self, gallery, parent_context=None):
        self.add_prev_next(gallery)
        return super().get_context(gallery, parent_context=parent_context)


class VideoChooserBlock(ChooserBlock):
    @cached_property
    def target_model(self):
        from .models import Video
        return Video

    @cached_property
    def widget(self):
        from .wagtail_widgets import AdminVideoChooser
        return AdminVideoChooser()

    def get_form_state(self, value):
        value_data = self.widget.get_value_data(value)
        if value_data is None:
            return None
        else:
            return {
                "id": value_data["id"],
                "edit_link": value_data["edit_url"],
                "title": value_data["title"],
                "preview": value_data["preview"],
            }

    def get_context(self, video, parent_context=None):
        print("get context: ", video)
        context = super().get_context(video, parent_context=parent_context)
        context["video"] = video
        return context

    class Meta:
        icon = "media"
