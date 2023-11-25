from collections.abc import Iterable
from itertools import chain, islice, tee
from typing import TYPE_CHECKING, Literal, Optional, Union

from django.db.models import QuerySet
from django.template.loader import TemplateDoesNotExist, get_template
from django.utils.functional import cached_property
from django.utils.safestring import mark_safe
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import ClassNotFound, get_lexer_by_name
from wagtail.blocks import CharBlock, ChooserBlock, ListBlock, StructBlock, TextBlock
from wagtail.images.blocks import ImageChooserBlock
from wagtail.images.models import AbstractImage, AbstractRendition, Image

from . import appsettings as settings
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


def calculate_thumbnail_width(original_width, original_height, rect_width, rect_height):
    # Calculate aspect ratios
    original_aspect_ratio = original_width / original_height
    rect_aspect_ratio = rect_width / rect_height

    # Determine if the image needs to be scaled based on width or height
    if original_aspect_ratio > rect_aspect_ratio:
        # Scale based on width
        thumbnail_width = rect_width
    else:
        # Scale based on height (maintain aspect ratio)
        thumbnail_width = rect_height * original_aspect_ratio

    return thumbnail_width


ImageFormat = Literal["jpeg", "avif", "webp"]


ImageFormats = list[ImageFormat]


class Thumbnail:
    def __init__(
        self,
        image: Image,
        slot_width: int,
        slot_height: int,
        max_scale_factor: int = 3,
        formats: ImageFormats = ["jpeg", "avif"],
    ) -> None:
        self.image = image
        self.formats: ImageFormats = formats
        thumbnail_width = round(calculate_thumbnail_width(image.width, image.height, slot_width, slot_height))
        self.renditions = {}
        for image_format in self.formats:
            self.renditions[image_format] = self.build_renditions(
                image, thumbnail_width, max_scale_factor=max_scale_factor, format=image_format
            )

    @staticmethod
    def build_renditions(
        image: AbstractImage, width: int, max_scale_factor: int = 3, format: str = "jpeg"
    ) -> list[AbstractRendition]:
        renditions = []
        for scale_factor in range(1, max_scale_factor + 1):
            scaled_width = width * scale_factor
            if scaled_width > image.width * 0.8:
                # already big enough
                continue
            renditions.append(image.get_rendition(f"width-{scaled_width}|format-{format}"))
        return renditions

    @property
    def src(self) -> dict[ImageFormat, str]:
        format_to_src = {}
        for image_format in self.formats:
            if len(self.renditions.get(image_format, [])) == 0:
                format_to_src[image_format] = getattr(self.image, "url", "")
            else:
                format_to_src[image_format] = self.renditions[image_format][0].url
        return format_to_src

    @property
    def srcset(self) -> dict[ImageFormat, str]:
        format_to_srcset = {}
        for image_format in self.formats:
            if len(self.renditions.get(image_format, [])) == 0:
                continue
            format_to_srcset[image_format] = ", ".join(
                f"{rendition.url} {rendition.width}w" for rendition in self.renditions[image_format]
            )
        return format_to_srcset

    @property
    def sizes(self) -> str:
        jpg_renditions = self.renditions["jpeg"]
        if len(jpg_renditions) == 0:
            return "100vw"
        return f"{jpg_renditions[0].width}px"

    @property
    def width(self) -> int:
        jpg_renditions = self.renditions["jpeg"]
        if len(jpg_renditions) == 0:
            return 0
        return jpg_renditions[0].width

    @property
    def height(self) -> int:
        jpg_renditions = self.renditions["jpeg"]
        if len(jpg_renditions) == 0:
            return 0
        return jpg_renditions[0].height


class CastImageChooserBlock(ImageChooserBlock):
    """
    Just add a thumbnail to the image because we then can use the thumbnail
    to get the srcset and sizes attributes in the template.
    """

    def get_context(self, image: AbstractImage, parent_context: Optional[dict] = None) -> dict:
        slot_width, slog_height = settings.CAST_IMAGE_SLOT_DIMENSIONS
        image.thumbnail = Thumbnail(image, slot_width, slog_height)
        return super().get_context(image, parent_context=parent_context)


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

    @staticmethod
    def add_image_thumbnails(gallery: QuerySet[Gallery]) -> None:
        thumbnail_slot_width, thumbnail_slot_height = settings.CAST_THUMBNAIL_SLOT_DIMENSIONS
        image_slot_width, image_slot_height = settings.CAST_IMAGE_SLOT_DIMENSIONS
        for image in gallery:
            image.thumbnail = Thumbnail(image, thumbnail_slot_width, thumbnail_slot_height)
            image.modal = Thumbnail(image, image_slot_width, image_slot_height)

    def get_context(self, gallery: QuerySet[Gallery], parent_context: Optional[dict] = None) -> dict:
        self.add_prev_next(gallery)
        self.add_image_thumbnails(gallery)
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
