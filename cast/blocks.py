from collections.abc import Iterable
from itertools import chain, islice, tee
from typing import TYPE_CHECKING, Union

from django.db.models import QuerySet
from django.template.loader import TemplateDoesNotExist, get_template
from django.utils.functional import cached_property
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import ClassNotFound, get_lexer_by_name
from wagtail.blocks import CharBlock, ChoiceBlock, ListBlock, StructBlock, TextBlock
from wagtail.images.blocks import ChooserBlock, ImageChooserBlock
from wagtail.images.models import AbstractImage, AbstractRendition, Image, Rendition

from . import appsettings as settings
from .cache import PostData
from .renditions import (
    Height,
    ImageForSlot,
    ImageType,
    Rectangle,
    RenditionFilters,
    Width,
)

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


def get_srcset_images_for_slots(
    image: AbstractImage,
    image_type: ImageType,
    fetched_renditions: dict[str, AbstractRendition] | None = None,
) -> dict[Rectangle, ImageForSlot]:
    """
    Get the srcset images for the given slots and image formats. This will fetch
    renditions from wagtail and return a list of ImageInSlot objects.
    """
    images_for_slots = {}
    rendition_filters = RenditionFilters.from_wagtail_image_with_type(image=image, image_type=image_type)
    slots, image_formats = rendition_filters.slots, rendition_filters.image_formats
    rendition_filter_strings = rendition_filters.filter_strings
    if len(rendition_filter_strings) > 0:
        renditions = {}
        if fetched_renditions is not None:
            renditions = fetched_renditions
        filter_strings_to_fetch = [fs for fs in rendition_filter_strings if fs not in renditions]
        if len(filter_strings_to_fetch) > 0:
            renditions.update(image.get_renditions(*filter_strings_to_fetch))
        rendition_filters.set_filter_to_url_via_wagtail_renditions(renditions)
    for slot in slots:
        try:
            images_for_slots[slot] = rendition_filters.get_image_for_slot(slot)
        except ValueError:
            # no fitting image found for slot -> use original image
            src = {}
            for image_format in image_formats:
                if image_format == rendition_filters.original_format:
                    src[image_format] = image.file.url
                else:
                    # convert to image_format
                    rendition = image.get_rendition(f"format-{image_format}")
                    src[image_format] = rendition.url
            srcset = {}
            for image_format in image_formats:
                if image_format == rendition_filters.original_format:
                    srcset[image_format] = f"{image.file.url} {image.width}w"
                else:
                    # convert to image_format
                    rendition = image.get_rendition(f"format-{image_format}")
                    srcset[image_format] = f"{rendition.url} {rendition.width}w"
            width = rendition_filters.slot_to_fitting_width[slot]
            images_for_slots[slot] = ImageForSlot(Rectangle(width, slot.height), src, srcset)
    return images_for_slots


class CastImageChooserBlock(ImageChooserBlock):
    """
    Just add a thumbnail to the image because we then can use the thumbnail
    to get the srcset and sizes attributes in the template.
    """

    def get_image_and_renditions(self, image_id, context: dict) -> tuple[Image, dict[str, Rendition]]:
        post_data: PostData | None = context.get("post_data")
        if post_data is None:
            print("image id? ", image_id)
            image = super().to_python(image_id)
            image_renditions = context.get("renditions_for_posts", {}).get(image.pk, [])
        else:
            image = post_data.images[image_id]
            image_renditions = post_data.renditions_for_posts.get(image.pk, [])
        fetched_renditions = {r.filter_spec: r for r in image_renditions}
        return image, fetched_renditions

    def get_context(self, image_or_pk: int | Image, parent_context: dict | None = None) -> dict:
        if parent_context is None:
            parent_context = {}
        if isinstance(image_or_pk, Image):
            # FIXME: dunno why this is here :/ 2024-03-14 Jochen
            image = image_or_pk
            image_pk = image.pk
        else:
            image_pk = image_or_pk
        image, fetched_renditions = self.get_image_and_renditions(image_pk, parent_context)
        images_for_slots = get_srcset_images_for_slots(image, "regular", fetched_renditions=fetched_renditions)
        [image.regular] = images_for_slots.values()
        return super().get_context(image, parent_context=parent_context)

    def bulk_to_python(self, items):
        """Overwrite this method to avoid database queries."""
        return items

    def extract_references(self, value):
        yield self.model_class, str(value), "", ""


def add_prev_next(images: Iterable[AbstractImage]) -> None:
    """
    For each image in the queryset, add the previous and next image.
    """
    for previous_image, current_image, next_image in previous_and_next(images):
        current_image.prev = "false" if previous_image is None else f"img-{previous_image.pk}"
        current_image.next = "false" if next_image is None else f"img-{next_image.pk}"


def add_image_thumbnails(images: Iterable[AbstractImage], context: dict) -> None:
    """
    For each image in the queryset, add the thumbnail and modal image data to the image.
    """
    modal_slot, thumbnail_slot = (
        Rectangle(Width(w), Height(h)) for w, h in settings.CAST_GALLERY_IMAGE_SLOT_DIMENSIONS
    )
    post_data = context.get("post_data")
    renditions_for_posts = {} if post_data is None else post_data.renditions_for_posts
    for image in images:
        image_renditions = renditions_for_posts.get(image.pk, [])
        fetched_renditions = {r.filter_spec: r for r in image_renditions}
        images_for_slots = get_srcset_images_for_slots(image, "gallery", fetched_renditions=fetched_renditions)
        image.modal = images_for_slots[modal_slot]
        image.thumbnail = images_for_slots[thumbnail_slot]


def prepare_context_for_gallery(images: Iterable[AbstractImage], context: dict) -> dict:
    """
    Add the previous and next image and the thumbnail and modal image data to each
    image of the gallery and then the images to the context.
    """
    add_prev_next(images)
    add_image_thumbnails(images, context=context)
    context["image_pks"] = ",".join([str(image.pk) for image in images])
    context["images"] = images
    return context


def get_gallery_block_template(default_template_name: str, context: dict | None, layout: str = "default") -> str:
    if context is None:
        return default_template_name

    template_base_dir = context.get("template_base_dir")
    if template_base_dir is None:
        return default_template_name

    if layout == "htmx":
        template_from_theme = f"cast/{template_base_dir}/gallery_htmx.html"
    else:
        template_from_theme = f"cast/{template_base_dir}/gallery.html"
    try:
        get_template(template_from_theme)
        return template_from_theme
    except TemplateDoesNotExist:
        return default_template_name


class GalleryBlock(ListBlock):
    class Meta:
        icon = "image"
        label = "Gallery"
        template = "cast/gallery.html"

    def get_template(self, images: QuerySet[AbstractImage] | None = None, context: dict | None = None) -> str:
        default_template_name = super().get_template(images, context)
        return get_gallery_block_template(default_template_name, context)

    def get_context(self, images: QuerySet[AbstractImage], parent_context: dict | None = None) -> dict:
        context = super().get_context(images, parent_context=parent_context)
        return prepare_context_for_gallery(images, context)


class GalleryBlockWithLayout(StructBlock):
    """
    A gallery block with a layout. The layout parameter controls
    which template is used to render the gallery.
    """

    gallery = GalleryBlock(ImageChooserBlock())
    layout = ChoiceBlock(
        choices=[
            ("default", _("Web Component with Modal")),
            ("htmx", _("HTMX based layout")),
        ],
        default="default",
    )
    post_data: PostData | None = None

    class Meta:
        icon = "image"
        label = "Gallery with Layout"
        template = "cast/gallery.html"

    def get_template(self, value=None, context=None):
        default_template_name = super().get_template(value, context)
        layout = "default"
        if value is not None:
            if (layout_from_value := value.get("layout")) is not None:
                layout = layout_from_value
        return get_gallery_block_template(default_template_name, context, layout=layout)

    def get_context(self, value, parent_context: dict | None = None):
        context = super().get_context(value, parent_context=parent_context)
        context["post_pk"] = context["page"].pk  # FIXME remove this?
        if isinstance(value["gallery"][0], dict) and self.post_data is not None:
            value = self._get_images_from_cache([value], self.post_data)[0]
        return prepare_context_for_gallery(value["gallery"], context)

    def _get_images_from_cache(self, values, post_data: PostData):
        images = []
        for item in values[0]["gallery"]:
            if isinstance(item, dict) and item.get("type") == "item":
                images.append(post_data.images[item["value"]])
            elif isinstance(item, int):
                images.append(post_data.images[item])
        values[0]["gallery"] = images
        return values

    def bulk_to_python(self, values):
        """Overwrite this method to be able to use the post_data images cache."""
        if self.post_data is not None:
            try:
                return self._get_images_from_cache(values, self.post_data)
            except KeyError:
                # if fetching from cache fails, just return super().bulk_to_python
                pass
        return super().bulk_to_python(values)


class VideoChooserBlock(ChooserBlock):
    post_data: PostData | None = None

    @cached_property
    def target_model(self) -> type["Video"]:
        from .models import Video

        return Video

    @cached_property
    def widget(self) -> "AdminVideoChooser":
        from .widgets import AdminVideoChooser

        return AdminVideoChooser()

    def get_form_state(self, value: Union["Video", int] | None) -> dict | None:
        return self.widget.get_value_data(value)

    def bulk_to_python(self, values):
        if self.post_data is not None:
            try:
                return [self.post_data.videos[value] for value in values]
            except KeyError:
                # if fetching from cache fails, just return super().bulk_to_python
                pass
        return super().bulk_to_python(values)


class AudioChooserBlock(ChooserBlock):
    post_data: PostData | None = None

    @cached_property
    def target_model(self) -> type["Audio"]:
        from .models import Audio

        return Audio

    @cached_property
    def widget(self):
        from .widgets import AdminAudioChooser

        return AdminAudioChooser()

    def get_form_state(self, value: Union["Video", int] | None) -> dict | None:
        return self.widget.get_value_data(value)

    def bulk_to_python(self, values):
        if self.post_data is not None:
            try:
                return [self.post_data.audios[value] for value in values]
            except KeyError:
                # if fetching from cache fails, just return super().bulk_to_python
                pass
        return super().bulk_to_python(values)


class CodeBlock(StructBlock):
    language = CharBlock(help_text="The language of the code block")
    source = TextBlock(rows=8, help_text="The source code of the block")

    def render_basic(self, value: dict | None, context=None) -> str:
        if value is not None:
            try:
                lexer = get_lexer_by_name(value["language"], stripall=True)
            except (ClassNotFound, KeyError):
                lexer = get_lexer_by_name("text", stripall=True)
            highlighted = highlight(value["source"], lexer, HtmlFormatter())
            return mark_safe(highlighted)
        else:
            return ""


def register_blocks_for_post_data() -> None:
    PostData.register_block(GalleryBlockWithLayout)
    PostData.register_block(VideoChooserBlock)
    PostData.register_block(AudioChooserBlock)


register_blocks_for_post_data()
