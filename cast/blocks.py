from collections.abc import Iterable
from itertools import chain, islice, tee
from typing import TYPE_CHECKING, Optional, Union

from django.db.models import QuerySet
from django.template.loader import TemplateDoesNotExist, get_template
from django.utils.functional import cached_property
from django.utils.safestring import mark_safe
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import ClassNotFound, get_lexer_by_name
from wagtail.blocks import CharBlock, ChooserBlock, ListBlock, StructBlock, TextBlock

from .models import Gallery

if TYPE_CHECKING:
    from .models import Audio, Video
    from .widgets import AdminVideoChooser


def previous_and_next(all_items: Iterable) -> Iterable:
    """
    Turn an iterable into an iterable of tuples of the
    previous and next item in the iterable.

    Example:
        >>> list(previous_and_next(range(3)))
        [(None, 0, 1), (0, 1, 2), (1, 2, None)]
    """
    previous_items, items, next_items = tee(all_items, 3)
    previous_items = chain([None], previous_items)
    next_items = chain(islice(next_items, 1, None), [None])
    return zip(previous_items, items, next_items)


class GalleryBlock(ListBlock):
    default_template_name = "cast/gallery.html"

    @staticmethod
    def add_prev_next(gallery: QuerySet[Gallery]) -> None:
        for previous_image, current_image, next_image in previous_and_next(gallery):
            current_image.prev = "false" if previous_image is None else f"img-{previous_image.pk}"
            current_image.next = "false" if next_image is None else f"img-{next_image.pk}"

    def get_template(self, context: Optional[dict] = None) -> str:
        if context is None:
            return self.default_template_name

        template_base_dir = context.get("template_base_dir")
        if template_base_dir is None:
            return self.default_template_name

        template_from_theme = f"cast/{template_base_dir}/gallery.html"
        try:
            get_template(template_from_theme)
            return template_from_theme
        except TemplateDoesNotExist:
            return self.default_template_name

    def get_context(self, gallery: QuerySet[Gallery], parent_context: Optional[dict] = None) -> dict:
        self.add_prev_next(gallery)
        return super().get_context(gallery, parent_context=parent_context)


class VideoChooserBlock(ChooserBlock):
    @cached_property
    def target_model(self) -> type["Video"]:
        from .models import Video

        return Video

    @cached_property
    def widget(self) -> "AdminVideoChooser":
        from .widgets import AdminVideoChooser

        return AdminVideoChooser()

    def get_form_state(self, value: Optional[Union["Video", int]]) -> Optional[dict]:
        return self.widget.get_value_data(value)


class AudioChooserBlock(ChooserBlock):
    @cached_property
    def target_model(self) -> type["Audio"]:
        from .models import Audio

        return Audio

    @cached_property
    def widget(self):
        from .widgets import AdminAudioChooser

        return AdminAudioChooser()

    def get_form_state(self, value: Optional[Union["Video", int]]) -> Optional[dict]:
        return self.widget.get_value_data(value)


class CodeBlock(StructBlock):
    language = CharBlock(help_text="The language of the code block")
    source = TextBlock(rows=8, help_text="The source code of the block")

    def render_basic(self, value: Optional[dict], context=None) -> str:
        if value is not None:
            try:
                lexer = get_lexer_by_name(value["language"], stripall=True)
            except (ClassNotFound, KeyError):
                lexer = get_lexer_by_name("text", stripall=True)
            highlighted = highlight(value["source"], lexer, HtmlFormatter())
            return mark_safe(highlighted)
        else:
            return ""
