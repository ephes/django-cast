from abc import abstractmethod
from collections.abc import Iterable
from itertools import chain, islice, tee
from typing import TYPE_CHECKING, Any, Protocol, Union

from django.db.models import Model, QuerySet
from django.template.loader import TemplateDoesNotExist, get_template
from django.utils.functional import cached_property
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import ClassNotFound, get_lexer_by_name
from wagtail.blocks import CharBlock, ChoiceBlock, ListBlock, StructBlock, TextBlock
from wagtail.blocks.list_block import ListValue
from wagtail.images.blocks import ChooserBlock, ImageChooserBlock
from wagtail.images.models import AbstractImage, AbstractRendition, Image, Rendition

from . import appsettings as settings
from .models.repository import AudioById, ImageById, RenditionsForPosts, VideoById
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
    renditions: dict[str, AbstractRendition],
) -> dict[Rectangle, ImageForSlot]:
    """
    Get the srcset images for the given slots and image formats. This will return a list of ImageInSlot objects.
    """
    images_for_slots = {}
    rendition_filters = RenditionFilters.from_wagtail_image_with_type(image=image, image_type=image_type)
    slots, image_formats = rendition_filters.slots, rendition_filters.image_formats
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
                    rendition = renditions[f"format-{image_format}"]
                    src[image_format] = rendition.url
            srcset = {}
            for image_format in image_formats:
                if image_format == rendition_filters.original_format:
                    srcset[image_format] = f"{image.file.url} {image.width}w"
                else:
                    rendition = renditions[f"format-{image_format}"]
                    srcset[image_format] = f"{rendition.url} {rendition.width}w"
            width = rendition_filters.slot_to_fitting_width[slot]
            images_for_slots[slot] = ImageForSlot(Rectangle(width, slot.height), src, srcset)
    return images_for_slots


class HasImagesAndRenditions(Protocol):
    image_by_id: ImageById
    renditions_for_posts: RenditionsForPosts


class EmptyImageRepository:
    """
    A repository that can be used if no repository was set.
    """

    image_by_id: ImageById = {}
    renditions_for_posts: RenditionsForPosts = {}


class ChooserGetPrepValueMixin:
    """
    A mixin for the ChooserBlock that allows to set the value to an integer.
    Without this, the page detail api endpoint throws an error because it
    expects an instance or None, but already gets an integer.
    See: https://github.com/ephes/django-cast/issues/157
    """

    def get_prep_value(self, value: Model | int | None) -> int | None:
        if isinstance(value, int):
            return value
        return super().get_prep_value(value)  # type: ignore


class GalleryImageChooserBlock(ImageChooserBlock):
    """
    Fix for https://github.com/ephes/django-cast/issues/157
    """

    def get_prep_value(self, value: Model | dict | None) -> int | None:
        if isinstance(value, dict):
            return value["value"]
        return super().get_prep_value(value)


class CastImageChooserBlock(ChooserGetPrepValueMixin, ImageChooserBlock):
    """
    Just add a thumbnail to the image because we then can use the thumbnail
    to get the srcset and sizes attributes in the template.
    """

    @staticmethod
    def get_image_and_renditions(image_id: int, context: dict) -> tuple[Image, dict[str, Rendition]]:
        repository: HasImagesAndRenditions = context["repository"]
        image = repository.image_by_id[image_id]
        image_renditions = repository.renditions_for_posts.get(image.pk, [])
        fetched_renditions = {r.filter_spec: r for r in image_renditions}
        return image, fetched_renditions

    def get_context(self, image_or_pk: int | Image, parent_context: dict) -> dict:
        assert parent_context is not None
        if isinstance(image_or_pk, int):
            image_pk = image_or_pk
        else:
            # In the preview mode, the image is already an Image object.
            # Do not try to remove this, it's really needed.
            image_pk = image_or_pk.pk
        image, fetched_renditions = self.get_image_and_renditions(image_pk, parent_context)
        images_for_slots = get_srcset_images_for_slots(image, "regular", renditions=fetched_renditions)
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
    Note: This function is kept for backward compatibility, but prev/next
    attributes are now calculated directly in templates to handle duplicates correctly.
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
    repository: HasRenditionsForPosts = context["repository"]
    renditions_for_posts = repository.renditions_for_posts
    for image in images:
        image_renditions = renditions_for_posts.get(image.pk, [])
        fetched_renditions = {r.filter_spec: r for r in image_renditions}
        images_for_slots = get_srcset_images_for_slots(image, "gallery", renditions=fetched_renditions)
        image.modal = images_for_slots[modal_slot]
        image.thumbnail = images_for_slots[thumbnail_slot]


def prepare_context_for_gallery(images: Iterable[AbstractImage], context: dict) -> dict:
    """
    Add the previous and next image and the thumbnail and modal image data to each
    image of the gallery and then the images to the context.
    """
    images_list = list(images)  # Ensure it's a list
    add_prev_next(images_list)
    add_image_thumbnails(images_list, context=context)
    context["image_pks"] = ",".join([str(image.pk) for image in images_list])
    context["images"] = images_list
    return context


def get_block_template(default_template_name: str, context: dict | None, *, file_name: str) -> str:
    """
    Get the template name for the block from the default template name, the context and the
    local file name. This is needed to be able to overwrite the default template with a
    theme specific template controlled by "template_base_dir" in the context.
    """
    if context is None:
        return default_template_name

    template_base_dir = context.get("template_base_dir")
    if template_base_dir is None:
        return default_template_name

    template_from_theme = f"cast/{template_base_dir}/{file_name}"
    try:
        get_template(template_from_theme)
        return template_from_theme
    except TemplateDoesNotExist:
        return default_template_name


class HasRenditionsForPosts(Protocol):
    renditions_for_posts: RenditionsForPosts


class GalleryProxyRepository:
    """
    A repository that can be used if no repository was set.
    """

    renditions_for_posts: RenditionsForPosts = {}


class GalleryBlock(ListBlock):
    class Meta:
        icon = "image"
        label = "Gallery"
        template = "cast/gallery.html"

    def dict_images_to_id_list(self, values: list[dict]) -> list[int]:
        parsed = []
        for item in values:
            parsed.append(item["value"])
        return parsed

    def get_form_state(self, value):
        """
        I don't know why this is needed, but it is needed to make the editor work
        for galleries. Do not try to remove it, or at least test if galleries are
        still working in the editor. FIXME.
        """
        if isinstance(value, (list, ListValue)):
            not_none_values = list(filter(None, value))
            image_ids = self.dict_images_to_id_list(not_none_values)
            return super().get_form_state(image_ids)
        return super().get_form_state(value)

    def get_template(self, images: QuerySet[AbstractImage] | None = None, context: dict | None = None) -> str:
        default_template_name = super().get_template(images, context)
        return get_block_template(default_template_name, context, file_name="gallery.html")

    def get_context(self, images: QuerySet[AbstractImage], parent_context: dict | None = None) -> dict:
        if parent_context is None:
            parent_context = {"repository": GalleryProxyRepository()}
        context = super().get_context(images, parent_context=parent_context)
        return prepare_context_for_gallery(images, context)


class GalleryBlockWithLayout(StructBlock):
    """
    A gallery block with a layout. The layout parameter controls
    which template is used to render the gallery.
    """

    gallery = GalleryBlock(GalleryImageChooserBlock())
    layout = ChoiceBlock(
        choices=[
            ("default", _("Web Component with Modal")),
            ("htmx", _("HTMX based layout")),
        ],
        default="default",
    )

    class Meta:
        icon = "image"
        label = "Gallery with Layout"
        template = "cast/gallery.html"

    def extract_references(self, value):
        # We don't have the gallery id at this point and not overwriting
        # this method will return a concatenated string of all image items
        # which will lead to postgres complaining about the length of the
        # `wagtailcore_referenceindex.to_object_id` field.
        return []

    def get_template(self, value=None, context=None):
        default_template_name = super().get_template(value, context)
        layout = "default"
        if value is not None:
            if (layout_from_value := value.get("layout")) is not None:
                layout = layout_from_value
        if layout == "htmx":
            template_file_name = "gallery_htmx.html"
        else:
            template_file_name = "gallery.html"
        return get_block_template(default_template_name, context, file_name=template_file_name)

    @staticmethod
    def _get_images_from_repository(repository: HasImagesAndRenditions, values):
        images = []
        for item in values["gallery"]:
            if isinstance(item, dict) and item.get("type") == "item":
                images.append(repository.image_by_id[item["value"]])
            else:
                # it's an Image object
                images.append(item)
        values["gallery"] = images
        return values

    def bulk_to_python(self, values):
        """Postpone the fetching of the database objects to the get_context method."""
        return values

    @staticmethod
    def bulk_to_python_from_database(values):
        image_ids_or_images = list(filter(None, values["gallery"]))
        if len(image_ids_or_images) == 0:
            return values
        if isinstance(image_ids_or_images[0], Image):
            return values
        image_ids_or_images = [item["value"] for item in image_ids_or_images]
        assert isinstance(image_ids_or_images[0], int)
        # we have to fetch the images from the database
        image_ids = image_ids_or_images
        # Fetch all images in one query but preserve the order
        images_by_id = {img.pk: img for img in Image.objects.filter(pk__in=image_ids)}
        # Reconstruct the list in the original order, allowing duplicates
        values["gallery"] = [images_by_id[pk] for pk in image_ids if pk in images_by_id]
        return values

    def from_repository_to_python(self, repository: HasImagesAndRenditions, values):
        try:
            return self._get_images_from_repository(repository, values)
        except KeyError:
            return self.bulk_to_python_from_database(values)

    def get_context(self, value, parent_context: dict | None = None):
        assert parent_context is not None
        repository = parent_context["repository"]
        value = self.from_repository_to_python(repository, value)
        context = super().get_context(value, parent_context=parent_context)
        return prepare_context_for_gallery(value["gallery"], context)


class RepositoryChooserBlock(ChooserGetPrepValueMixin, ChooserBlock):
    def bulk_to_python(self, values):
        """
        Postpone the fetching of the database objects to the get_context method
        because the repository is not available in the bulk_to_python method.
        """
        return values

    def extract_references(self, value):
        yield self.model_class, str(value), "", ""

    @abstractmethod
    def from_repository_to_python(self, repository: Any, value: int) -> Model:
        raise NotImplementedError

    def get_context(self, value, parent_context=None):
        repository = parent_context["repository"]
        value = self.from_repository_to_python(repository, value)
        return super().get_context(value, parent_context=parent_context)


class HasVideos(Protocol):
    video_by_id: VideoById


class VideoChooserBlock(RepositoryChooserBlock):
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

    def from_repository_to_python(self, repository: HasVideos, value: int) -> Model:
        if isinstance(value, self.target_model):
            # this happens in the edit / preview mode
            return value
        try:
            return repository.video_by_id[value]
        except KeyError:
            return super().to_python(value)


class HasAudios(Protocol):
    audio_by_id: AudioById


class AudioChooserBlock(RepositoryChooserBlock):
    def get_template(self, value=None, context=None):
        default_template_name = super().get_template(value, context)
        return get_block_template(default_template_name, context, file_name="audio.html")

    @cached_property
    def target_model(self) -> type["Audio"]:
        from .models import Audio

        return Audio

    @cached_property
    def widget(self):
        from .widgets import AdminAudioChooser

        return AdminAudioChooser()

    def get_form_state(self, value: Union["Audio", int] | None) -> dict | None:
        return self.widget.get_value_data(value)

    def from_repository_to_python(self, repository: HasAudios, value: int) -> Model:
        if isinstance(value, self.target_model):
            # this happens in the edit / preview mode
            return value
        try:
            return repository.audio_by_id[value]
        except KeyError:
            return super().to_python(value)

    def get_prep_value(self, value):
        """
        This is called with an int value when a page with audio is retrieved
        via the API like this: /api/wagtail/pages/67/
        """
        if isinstance(value, int):
            return value
        return super().get_prep_value(value)


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
