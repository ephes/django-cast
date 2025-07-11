from typing import cast

import pytest
from wagtail.images.blocks import ImageChooserBlock
from wagtail.images.models import AbstractImage, AbstractRendition, Image

from cast.blocks import (
    AudioChooserBlock,
    CastImageChooserBlock,
    CodeBlock,
    GalleryBlock,
    GalleryBlockWithLayout,
    GalleryProxyRepository,
    VideoChooserBlock,
    get_srcset_images_for_slots,
)
from cast.models import Audio, Gallery, Video
from cast.renditions import IMAGE_TYPE_TO_SLOTS, Height, Width


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, ""),  # make sure None is rendered as empty string
        (  # make sure source is rendered even if language is not found
            {"language": "nonexistent", "source": "blub"},
            '<div class="highlight"><pre><span></span>blub\n</pre></div>\n',
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
def test_gallery_block_template_defauflt(context):
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


class StubRendition:
    def __init__(self, url, filter_spec, width):
        self.url = url
        self.filter_spec = filter_spec
        self.width = width


def test_get_srcset_images_for_slots_use_original_if_image_too_small():
    # Given an image that is too small for the slot
    slot = IMAGE_TYPE_TO_SLOTS["gallery"][0]
    stub_image = Stub1PxImage()
    renditions = {
        "format-avif": StubRendition("https://example.com/test.avif", "format-avif", stub_image.width),
    }
    images_for_slots = get_srcset_images_for_slots(cast(AbstractImage, stub_image), "gallery", renditions=renditions)
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
    renditions = {
        "width-1110": rendition,
        "width-2220": rendition,
        "width-3330": rendition,
        "width-1110|format-avif": rendition,
        "width-2220|format-avif": rendition,
        "width-3330|format-avif": rendition,
    }
    images_for_slot = get_srcset_images_for_slots(image, "regular", renditions=renditions)
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
    images_for_slot = get_srcset_images_for_slots(image, "regular", renditions=fetched_renditions)
    assert images_for_slot[slot].src["jpeg"] == "https://example.com/test.jpg"


@pytest.mark.django_db
def test_gallery_block_get_context_parent_context_none():
    """Just make sure parent context is set to {} if it is None."""
    cb = GalleryBlock(ImageChooserBlock())
    context = cb.get_context(Gallery.objects.none(), parent_context=None)
    assert "value" in context

    cb = GalleryBlock(ImageChooserBlock())
    context = cb.get_context([], parent_context={"repository": GalleryProxyRepository()})
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
    values = block._get_images_from_repository(None, {"gallery": []})
    assert values["gallery"] == []


def test_gallery_block_with_layout_return_early():
    block = GalleryBlockWithLayout()

    # no images
    values = block.bulk_to_python_from_database({"gallery": []})
    assert values == {"gallery": []}

    # real images
    values_in = {"gallery": [Image(id=1, title="Some image", collection=None)]}
    values_out = block.bulk_to_python_from_database(values_in)
    assert values_out == values_in


def test_gallery_block_with_layout_from_repository_to_python(mocker):
    class Image:
        pk = 1

    class Repository:
        image_by_id: dict = {}
        renditions_for_posts: dict = {}

    block = GalleryBlockWithLayout()

    # values ist not a list of image dicts, but a list of images
    values = {
        "gallery": [Image()],
    }
    result = block.from_repository_to_python(Repository(), values)
    assert result == values

    # values raises a KeyError and bulk_to_python_from_database is called
    mocker.patch.object(block, "bulk_to_python_from_database", return_value=values)
    result = block.from_repository_to_python(Repository(), {})
    assert result == values


@pytest.mark.django_db
def test_gallery_block_with_layout_bulk_to_python_from_database(image):
    block = GalleryBlockWithLayout()
    values = {"gallery": [{"type": "item", "value": image.pk}]}
    result = block.bulk_to_python_from_database(values)
    assert result == {"gallery": [image]}


@pytest.mark.django_db
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

    class Repository:
        image_by_id = {1: Image()}
        renditions_for_posts = {}

    block = GalleryBlockWithLayout()
    with pytest.raises(ValueError):
        block.get_context(
            {"gallery": [{"type": "item", "value": 1}]},
            {"template_base_dir": "bootstrap4", "page": Page(), "repository": Repository()},
        )


@pytest.mark.django_db
def test_gallery_block_get_form_state(image):
    block = GalleryBlock(ImageChooserBlock())
    # empty input -> empty output
    items = block.get_form_state([])
    assert items == []

    # input with one item
    items = block.get_form_state([{"type": "item", "value": image.pk}])
    assert items[0]["value"]["id"] == image.pk

    # input with a tuple (to test against else of isinstance)
    items = block.get_form_state((image.pk,))
    assert items[0]["value"]["id"] == image.pk


@pytest.mark.django_db
def test_audio_chooser_from_repository_to_python_database(audio):
    class Repository:
        audio_by_id = {}

    block = AudioChooserBlock()
    model = block.from_repository_to_python(Repository(), audio.pk)
    assert model == audio


def test_audio_chooser_block_from_repository_to_python_return_early():
    class Repository:
        audio_by_id = {}

    audio = Audio(id=1, title="Some audio", collection=None)

    block = AudioChooserBlock()
    model = block.from_repository_to_python(Repository(), audio)
    assert model == audio


def test_audio_chooser_block_get_prep_value_int_or_none():
    # this happens when /api/pages/23/ is called
    block = AudioChooserBlock()
    value = block.get_prep_value(1)
    assert value == 1

    # for coverage test None
    value = block.get_prep_value(None)
    assert value is None


@pytest.mark.django_db
def test_video_chooser_from_repository_to_python_database(video):
    class Repository:
        video_by_id = {}

    block = VideoChooserBlock()
    model = block.from_repository_to_python(Repository(), video.pk)
    assert model == video


def test_video_chooser_block_from_repository_to_python_return_early():
    class Repository:
        video_by_id = {}

    video = Video(id=1, title="Some video", collection=None)

    block = VideoChooserBlock()
    model = block.from_repository_to_python(Repository(), video)
    assert model == video


class EmptyRepository:
    image_by_id: dict = {}
    renditions_for_posts: dict = {}


class Rendition:
    def __init__(self, filter_spec, url):
        self.filter_spec = filter_spec
        self.url = url


@pytest.mark.django_db
def test_image_chooser_block_get_context_image_or_pk(image):
    """Make sure get_context handles both an image or an image pk."""
    cicb = CastImageChooserBlock()
    repository = EmptyRepository()
    repository.image_by_id = {image.pk: image}
    repository.renditions_for_posts = {
        image.pk: [
            Rendition("format-jpeg", "https://example.com/test.jpg"),
            Rendition("format-avif", "https://example.com/test.avif"),
        ]
    }
    context = cicb.get_context(image, parent_context={"repository": repository})
    assert context["value"] == image
    context = cicb.get_context(image.pk, parent_context={"repository": repository})
    assert context["value"] == image


class TestAddPrevNext:
    """#171 Test the add_prev_next function."""

    pytestmark = pytest.mark.django_db

    def test_add_prev_next_with_duplicates(self):
        """#171 Test that add_prev_next works with duplicate images using PK-based navigation."""
        from cast.blocks import add_prev_next

        # Create images with duplicate PKs to simulate the same image used multiple times
        # In reality, we'd use existing images multiple times, but for testing
        # we just need objects with the pk attribute
        images = []
        for i in range(5):
            img = Image()
            img.pk = i % 3  # This creates PKs: 0, 1, 2, 0, 1
            images.append(img)

        # Apply add_prev_next
        add_prev_next(images)

        # Check that each image has correct prev/next based on PK
        # Note: Navigation is now handled in templates for proper duplicate support
        assert images[0].prev == "false"
        assert images[0].next == "img-1"

        assert images[1].prev == "img-0"
        assert images[1].next == "img-2"

        assert images[2].prev == "img-1"
        assert images[2].next == "img-0"  # Points to next image's PK (0)

        assert images[3].prev == "img-2"
        assert images[3].next == "img-1"  # Points to next image's PK (1)

        assert images[4].prev == "img-0"  # Points to previous image's PK (0)
        assert images[4].next == "false"

    def test_add_prev_next_single_image(self):
        """#171 Test that add_prev_next works with a single image."""
        from cast.blocks import add_prev_next

        img = Image()
        img.pk = 1
        images = [img]

        add_prev_next(images)

        assert images[0].prev == "false"
        assert images[0].next == "false"

    def test_add_prev_next_empty_list(self):
        """#171 Test that add_prev_next handles empty list gracefully."""
        from cast.blocks import add_prev_next

        images = []

        # Should not raise any exceptions
        add_prev_next(images)

        assert len(images) == 0

    def test_add_prev_next_all_same_pk(self):
        """#171 Test edge case where all images have the same PK."""
        from cast.blocks import add_prev_next

        images = []
        for _ in range(4):
            img = Image()
            img.pk = 42
            images.append(img)

        add_prev_next(images)

        # With PK-based navigation, all images point to the same PK
        # This demonstrates why template-based navigation is necessary
        for i, img in enumerate(images):
            if i == 0:
                assert img.prev == "false"
                assert img.next == "img-42"  # Points to next image's PK
            elif i == len(images) - 1:
                assert img.prev == "img-42"  # Points to previous image's PK
                assert img.next == "false"
            else:
                assert img.prev == "img-42"  # All point to same PK
                assert img.next == "img-42"  # All point to same PK
