from typing import cast

import pytest
from wagtail.images.blocks import ImageChooserBlock
from wagtail.images.models import AbstractImage, AbstractRendition

from cast.blocks import (
    CastImageChooserBlock,
    CodeBlock,
    GalleryBlock,
    GalleryBlockWithLayout,
    get_srcset_images_for_slots,
)
from cast.models import Gallery
from cast.renditions import IMAGE_TYPE_TO_SLOTS, Height, Rectangle, Width


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, ""),  # make sure None is rendered as empty string
        (  # make sure source is rendered even if language is not found
            {"language": "nonexistent", "source": "blub"},
            '<div class="highlight"><pre><span></span>blub\n' "</pre></div>\n",
        ),
        (  # happy path
            {
                "language": "python",
                "source": "print('hello world!')",
            },
            (
                '<div class="highlight"><pre><span></span><span class="nb">print'
                '</span><span class="p">(</span><span class="s1">&#39;hello world!&#39;'
                '</span><span class="p">)</span>\n'
                "</pre></div>\n"
            ),
        ),
    ],
)
def test_code_block_value(value, expected):
    block = CodeBlock()
    rendered = block.render_basic(value)
    assert rendered == expected


@pytest.mark.parametrize(
    "context",
    [
        None,  # context is None
        {},  # template_base_dir not in context
        {"template_base_dir": "nonexistent"},  # template_base_dir does not exist
    ],
)
def test_gallery_block_template_default(context):
    block = GalleryBlock(ImageChooserBlock())
    assert block.get_template(images=None, context=context) == block.meta.template


def test_gallery_block_template_from_theme(mocker):
    mocker.patch("cast.blocks.get_template")
    block = GalleryBlock(ImageChooserBlock())
    template_name = block.get_template(context={"template_base_dir": "vue"})
    assert template_name == "cast/vue/gallery.html"


class StubWagtailImage:
    class File:
        name = "test.jpg"
        url = "https://example.com/test.jpg"

    width = Width(6000)
    height = Height(4000)
    file = File()

    @staticmethod
    def get_renditions(*filter_strings):
        class StubImage:
            url = "https://example.com/test.jpg"
            width = Width(120)

        return {fs: StubImage() for fs in filter_strings}


def test_get_srcset_images_for_slots_get_renditions_is_called_when_filters_not_empty():
    # Given an image that should generate multiple renditions for a slot
    slot = Rectangle(Width(120), Height(80))
    images_for_slots = get_srcset_images_for_slots(cast(AbstractImage, StubWagtailImage()), "gallery")
    # When we get the srcset images for the slot
    image_for_slot = images_for_slots[slot]
    split_srcset = image_for_slot.srcset["jpeg"].replace(",", "").split(" ")  # type: ignore
    srcset_widths = sorted([int(t.rstrip("w")) for t in split_srcset if t.endswith("w")])
    # Then the srcset widths should be 120 * 1, 120 * 2, 120 * 3
    assert srcset_widths == [120, 240, 360]


class Stub1PxImage:
    class File:
        name = "test.jpg"
        url = "https://example.com/test.jpg"

    width = Width(1)
    height = Height(1)
    file = File()

    @staticmethod
    def get_rendition(_filter_string):
        class Avif:
            url = "https://example.com/test.avif"
            width = Width(1)

        return Avif()


def test_get_srcset_images_for_slots_use_original_if_image_too_small():
    # Given an image that is too small for the slot
    slot = IMAGE_TYPE_TO_SLOTS["gallery"][0]
    images_for_slots = get_srcset_images_for_slots(cast(AbstractImage, Stub1PxImage()), "gallery")
    # When we get the srcset images for the slot
    image_for_slot = images_for_slots[slot]
    # Then the image for the slot should be the original image
    assert image_for_slot.src["jpeg"] == "https://example.com/test.jpg"
    assert image_for_slot.srcset["jpeg"] == "https://example.com/test.jpg 1w"
    # And it should have been converted to avif
    assert image_for_slot.src["avif"] == "https://example.com/test.avif"
    assert image_for_slot.srcset["avif"] == "https://example.com/test.avif 1w"


class StubBigImage:
    class File:
        name = "test.jpg"
        url = "https://example.com/test.jpg"

    url = "https://example.com/test.jpg"
    width = Width(6000)
    height = Height(4000)
    file = File()

    @staticmethod
    def get_renditions(*filter_strings):
        class StubImage:
            url = "https://example.com/test.jpg"
            width = Width(120)

        return {fs: StubImage() for fs in filter_strings}


def test_get_srcset_images_for_slots_fetched_renditions_not_none():
    [slot] = IMAGE_TYPE_TO_SLOTS["regular"]
    rendition = cast(AbstractRendition, StubBigImage())
    image = cast(AbstractImage, StubBigImage())
    images_for_slot = get_srcset_images_for_slots(image, "regular", fetched_renditions={"width-1110": rendition})
    assert images_for_slot[slot].src["jpeg"] == "https://example.com/test.jpg"


def test_get_srcset_images_for_slots_fetched_renditions_contain_all_filter_strings():
    [slot] = IMAGE_TYPE_TO_SLOTS["regular"]
    rendition = cast(AbstractRendition, StubBigImage())
    image = cast(AbstractImage, StubBigImage())
    all_filter_strings = [
        "width-1110",
        "width-2220",
        "width-3330",
        "width-1110|format-avif",
        "width-2220|format-avif",
        "width-3330|format-avif",
    ]
    fetched_renditions = {fs: rendition for fs in all_filter_strings}
    images_for_slot = get_srcset_images_for_slots(image, "regular", fetched_renditions=fetched_renditions)
    assert images_for_slot[slot].src["jpeg"] == "https://example.com/test.jpg"


@pytest.mark.django_db
def test_image_chooser_block_get_context_parent_context_none(image):
    """Just make sure parent context is set to {} if it is None."""
    cicb = CastImageChooserBlock()
    context = cicb.get_context(image.pk, parent_context=None)
    assert "value" in context


@pytest.mark.django_db
def test_image_chooser_block_get_context_image_or_pk(image):
    """Make sure get_context handles both an image or an image pk."""
    cicb = CastImageChooserBlock()
    context = cicb.get_context(image, parent_context=None)
    assert context["value"] == image
    context = cicb.get_context(image.pk, parent_context=None)
    assert context["value"] == image


def test_gallery_block_get_context_parent_context_none():
    """Just make sure parent context is set to {} if it is None."""
    cb = GalleryBlock(ImageChooserBlock())
    context = cb.get_context(Gallery.objects.none(), parent_context=None)
    assert "value" in context


def test_gallery_block_with_layout_get_template_htmx():
    block = GalleryBlockWithLayout()
    template = block.get_template({"layout": "htmx"}, context={"template_base_dir": "bootstrap4"})
    assert template == "cast/bootstrap4/gallery_htmx.html"


def test_gallery_block_with_layout_get_template_value_is_none():
    block = GalleryBlockWithLayout()
    template = block.get_template(None, context={"template_base_dir": "bootstrap4"})
    assert template == "cast/bootstrap4/gallery.html"

    template = block.get_template({}, context={"template_base_dir": "bootstrap4"})
    assert template == "cast/bootstrap4/gallery.html"


def test_gallery_block_with_layout_get_empty_images_from_cache():
    block = GalleryBlockWithLayout()

    # no images
    values = block._get_images_from_cache([{"gallery": []}], None)
    assert values[0]["gallery"] == []

    # images which don't have type dict or int
    values = block._get_images_from_cache([{"gallery": [None]}], None)
    assert values[0]["gallery"] == []


def test_gallery_block_with_layout_get_context():
    class Page:
        pk = 1

    class File:
        name = ""

    class Image:
        pk = 1
        prev = None
        next = None
        file = File()

    class PostData:
        images = {1: Image()}

    block = GalleryBlockWithLayout()
    block.post_data = PostData()
    with pytest.raises(ValueError):
        block.get_context(
            {"gallery": [{"type": "item", "value": 1}]},
            {"template_base_dir": "bootstrap4", "page": Page()},
        )
