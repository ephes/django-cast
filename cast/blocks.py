from itertools import chain, islice, tee

from django.utils.functional import cached_property
from django.utils.safestring import mark_safe
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from wagtail.core.blocks import (
    CharBlock,
    ChooserBlock,
    ListBlock,
    StructBlock,
    TextBlock,
)


def previous_and_next(iterable):
    prevs, items, nexts = tee(iterable, 3)
    prevs = chain([None], prevs)
    nexts = chain(islice(nexts, 1, None), [None])
    return zip(prevs, items, nexts)


class GalleryBlock(ListBlock):
    class Meta:
        template = "cast/gallery.html"

    def add_prev_next(self, gallery):
        for previous_image, current_image, next_image in previous_and_next(gallery):
            current_image.prev = "false" if previous_image is None else f"img-{previous_image.pk}"
            current_image.next = "false" if next_image is None else f"img-{next_image.pk}"

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
        from .widgets import AdminVideoChooser

        return AdminVideoChooser()

    def get_form_state(self, value):
        return self.widget.get_value_data(value)


class AudioChooserBlock(ChooserBlock):
    @cached_property
    def target_model(self):
        from .models import Audio

        return Audio

    @cached_property
    def widget(self):
        from .widgets import AdminAudioChooser

        return AdminAudioChooser()

    def get_form_state(self, value):
        return self.widget.get_value_data(value)


class CodeBlock(StructBlock):
    language = CharBlock(help_text="The language of the code block")
    source = TextBlock(rows=8, help_text="The source code of the block")

    def render_basic(self, value, context=None):
        if value:
            lexer = get_lexer_by_name(value["language"], stripall=True)
            highlighted = highlight(value["source"], lexer, HtmlFormatter())
            return mark_safe(highlighted)
        else:
            return ""
