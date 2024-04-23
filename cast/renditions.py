from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NewType, cast, get_args

from wagtail.images.models import AbstractImage, AbstractRendition

from . import appsettings

Width = NewType("Width", int)
Height = NewType("Height", int)


@dataclass
class Rectangle:
    """
    Just a simple class to hold width and height. It is hashable to be used as a key
    when getting all renditions for a slot represented by a rectangle.
    """

    width: Width
    height: Height

    def __eq__(self, other):
        if not isinstance(other, Rectangle):
            raise ValueError(f"Can't compare RectDimension with {type(other)}")
        return (self.width, self.height) == (other.width, other.height)

    def __hash__(self):
        return hash((self.width, self.height))


def calculate_fitting_width(image: Rectangle, slot: Rectangle) -> Width:
    """
    Calculate the width of an image that fits into a rectangular slot.

    Returns the width the image needs to be scaled to in order to fit into the rect.
    """

    # Calculate aspect ratios
    image_aspect_ratio = image.width / image.height
    rect_aspect_ratio = slot.width / slot.height

    # Determine if the image needs to be scaled based on width or height
    if image_aspect_ratio > rect_aspect_ratio:
        # Scale based on width
        fitting_width = slot.width
    else:
        # Scale based on height (maintain aspect ratio)
        fitting_width = Width(round(slot.height * image_aspect_ratio))

    return fitting_width


ImageType = Literal["regular", "gallery"]
ImageFormat = Literal["jpeg", "avif", "webp", "png", "svg"]
SUPPORTED_IMAGE_FORMATS = set(get_args(ImageFormat))
ImageFormats = Iterable[ImageFormat]
IMAGE_TYPE_TO_SLOTS: dict[ImageType, list[Rectangle]] = {
    "regular": [Rectangle(Width(w), Height(h)) for w, h in appsettings.CAST_REGULAR_IMAGE_SLOT_DIMENSIONS],
    "gallery": [Rectangle(Width(w), Height(h)) for w, h in appsettings.CAST_GALLERY_IMAGE_SLOT_DIMENSIONS],
}
DEFAULT_IMAGE_FORMATS = cast(ImageFormats, appsettings.CAST_IMAGE_FORMATS)


@dataclass
class RenditionFilter:
    """
    A rendition filter for an image that fits into a slot.
    """

    width: Width  # width of the rendition
    slot: Rectangle  # slot the image needs to fit into
    format: ImageFormat  # desired image format

    def get_wagtail_filter_str(self, original_format: ImageFormat) -> str:
        """Return the filter string in wagtail format."""
        filter_parts = [f"width-{self.width}"]
        if self.format != original_format:
            filter_parts.append(f"format-{self.format}")
        return "|".join(filter_parts)


@dataclass
class FormatRenditionFilter(RenditionFilter):
    """
    A rendition filter for format conversion only.
    """

    def get_wagtail_filter_str(self, _original_format: ImageFormat) -> str:
        return f"format-{self.format}"


def get_rendition_filters_for_image_and_slot(
    image: Rectangle,  # dimensions of the original image
    slot: Rectangle,  # slot the image needs to fit into
    image_format: ImageFormat,  # desired image format
    max_scale_factor: int = 3,  # don't scale up renditions more than this
) -> list[RenditionFilter]:
    """
    Get a list of rendition filters for an image that has to fit into a slot.
    Don't scale up renditions more than max_scale_factor. If the rendition_width
    is nearly as big as the image_width, don't create an additional rendition filter.
    """
    filters = []
    fitting_width = calculate_fitting_width(image, slot)
    for pixel_density in range(1, max_scale_factor + 1):
        rendition_width = Width(fitting_width * pixel_density)
        if rendition_width > image.width * 0.8:
            # already big enough
            continue
        filters.append(RenditionFilter(width=rendition_width, slot=slot, format=image_format))
    return filters


def get_image_format_by_name(file_name: str) -> ImageFormat:
    """Guess the image format from the file name."""
    suffix_to_format: dict[str, ImageFormat] = {
        "jpg": "jpeg",
    }
    suffix = Path(file_name).suffix.lower().strip().lstrip(".")
    suffix = suffix_to_format.get(suffix, suffix)
    if suffix not in SUPPORTED_IMAGE_FORMATS:
        raise ValueError(f"Image format {suffix} not supported.")
    else:
        return cast(ImageFormat, suffix)


class ImageForSlot:
    """
    Image fitting into a slot. It has a src and a srcset for all image formats.
    Its purpose is to be used in a <picture> or <img> tag in a django template.
    It is potentially a lot smaller than the slot.

    For example if there's a slot of 120x80 and an image of 4000x6000, the image
    for the slot is 53x80. The srcset contains renditions of 53, 106 and 159 pixels.
    """

    def __init__(
        self,
        image: Rectangle,
        src: dict[ImageFormat, str],
        srcset: dict[ImageFormat, str],
    ) -> None:
        self.width = image.width
        self.height = image.height
        self.sizes = f"{self.width}px"
        self.src = src
        self.srcset = srcset


Filters = dict[Rectangle, dict[ImageFormat, list[RenditionFilter]]]


class RenditionFilters:
    def __init__(
        self,
        *,
        image: Rectangle,
        original_format: ImageFormat,
        slots: list[Rectangle],
        image_formats: ImageFormats,
    ) -> None:
        super().__init__()
        self.image = image
        self.original_format = original_format
        self.image_formats = image_formats
        self.slots = slots
        self.slot_to_fitting_width: dict[Rectangle, Width] = {}
        for slot in slots:
            self.slot_to_fitting_width[slot] = Width(calculate_fitting_width(image, slot))
        self.filters = self.build_filters()
        self.filter_to_url: dict[str, str] = {}

    @classmethod
    def from_wagtail_image(cls, image: AbstractImage, slots: list[Rectangle], image_formats: ImageFormats):
        original_format = get_image_format_by_name(image.file.name)
        image = Rectangle(Width(image.width), Height(image.height))
        return cls(image=image, original_format=original_format, slots=slots, image_formats=image_formats)

    @classmethod
    def from_wagtail_image_with_type(cls, image: AbstractImage, image_type: ImageType):
        return cls.from_wagtail_image(
            image, slots=IMAGE_TYPE_TO_SLOTS[image_type], image_formats=DEFAULT_IMAGE_FORMATS
        )

    def set_filter_to_url_via_wagtail_renditions(self, renditions: dict[str, AbstractRendition]) -> None:
        # self.filter_to_url = {fs: renditions[fs].url for fs in self.filter_strings}
        self.filter_to_url = {fs: renditions[fs].url for fs in renditions}

    def build_filters(self) -> Filters:
        """
        Build all filters for all slots and image formats.
        """
        slots, image = self.slots, self.image
        image_formats, original_format = self.image_formats, self.original_format
        filters: Filters = {slot: {} for slot in slots}
        for slot in slots:
            for image_format in image_formats:
                filters[slot][image_format] = format_filters = get_rendition_filters_for_image_and_slot(
                    image, slot, image_format
                )
                if len(format_filters) == 0 and image_format != original_format:
                    # if no filters found for the image format and the image format is not the original format
                    # add a format filter to convert the image to the desired format. This happens if the image
                    # is too small to be scaled to the slot.
                    fitting_width = self.slot_to_fitting_width[slot]
                    format_filters.append(FormatRenditionFilter(slot=slot, width=fitting_width, format=image_format))
        return filters

    def get_filter_by_slot_format_and_fitting_width(
        self, slot: Rectangle, image_format: ImageFormat, fitting_width: Width
    ) -> RenditionFilter:
        """
        Get a rendition filter by format and width. Raise ValueError if no filter found
        or more than one filter found.
        """
        filters = [f for f in self.filters[slot][image_format] if f.width == fitting_width]
        if len(filters) == 0:
            raise ValueError(f"No filter found for format {image_format} and width {fitting_width}")
        if len(filters) > 1:
            raise ValueError(f"More than one filter found for format {image_format} and width {fitting_width}")
        return filters[0]

    @staticmethod
    def get_all_filters(filters: dict[Rectangle, dict[ImageFormat, list[RenditionFilter]]]) -> list[RenditionFilter]:
        """
        Return a flat list of all filters.
        """
        all_filters = []
        for slot_filters in filters.values():
            for format_filters in slot_filters.values():
                all_filters.extend(format_filters)
        return all_filters

    @property
    def all_filters(self) -> list[RenditionFilter]:
        return self.get_all_filters(self.filters)

    def get_filter_strings(self, original_format: ImageFormat) -> list[str]:
        """
        Return a list of filter strings in wagtail format.
        """
        return [f.get_wagtail_filter_str(original_format) for f in self.all_filters]

    @property
    def filter_strings(self) -> list[str]:
        """
        Return a list of filter strings in wagtail format.
        """
        return self.get_filter_strings(self.original_format)

    def get_src_for_slot(self, slot: Rectangle) -> dict[ImageFormat, str]:
        src = {}
        fitting_width = self.slot_to_fitting_width[slot]
        for image_format in self.image_formats:
            format_filter = self.get_filter_by_slot_format_and_fitting_width(slot, image_format, fitting_width)
            format_filter_string = format_filter.get_wagtail_filter_str(self.original_format)
            url = self.filter_to_url.get(format_filter_string)
            if url is not None:  # pragma: no cover
                # FIXME this only happens during tests, dunno why - probably a wagtail bug
                src[image_format] = url
        return src

    def get_srcset_for_slot(self, slot: Rectangle) -> dict[ImageFormat, str]:
        srcset = {}
        filters_for_slot = self.filters[slot]
        for image_format in self.image_formats:
            filters_for_format = filters_for_slot[image_format]
            filter_strings_for_format = [f.get_wagtail_filter_str(self.original_format) for f in filters_for_format]
            # FIXME sometimes there's no url for a filter string, dunno why - probably a wagtail bug
            # this only happens during tests
            urls_for_filters = filter(None, (self.filter_to_url.get(fs) for fs in filter_strings_for_format))
            srcset_parts = []
            for url, filter_string in zip(urls_for_filters, filters_for_format):
                srcset_parts.append(f"{url} {filter_string.width}w")
            srcset[image_format] = ", ".join(srcset_parts)
        return srcset

    def get_image_for_slot(self, slot: Rectangle) -> ImageForSlot:
        src = self.get_src_for_slot(slot)
        srcset = self.get_srcset_for_slot(slot)
        fitting_image = Rectangle(width=self.slot_to_fitting_width[slot], height=slot.height)
        return ImageForSlot(image=fitting_image, src=src, srcset=srcset)
