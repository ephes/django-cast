from typing import cast
from types import SimpleNamespace

import pytest
from django.template.loader import get_template
from wagtail.images.blocks import ImageChooserBlock
from wagtail.images.models import AbstractImage, AbstractRendition, Image

import cast.renditions as renditions
from cast.blocks import (
    AudioChooserBlock,
    CastImageChooserBlock,
    CodeBlock,
    GalleryBlock,
    GalleryBlockWithLayout,
    GalleryImageChooserBlock,
    GalleryProxyRepository,
    VideoChooserBlock,
    get_srcset_images_for_slots,
    prepare_context_for_gallery,
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


def test_gallery_block_template_from_plain_theme():
    block = GalleryBlock(ImageChooserBlock())
    template_name = block.get_template(context={"template_base_dir": "plain"})
    assert template_name == "cast/plain/gallery.html"


def test_fallback_gallery_template_uses_bootstrap4_web_component():
    image = SimpleNamespace(
        default_alt_text="alt text",
        modal=SimpleNamespace(
            src=SimpleNamespace(avif="https://example.com/modal.avif", jpeg="https://example.com/modal.jpeg"),
            srcset=SimpleNamespace(
                avif="https://example.com/modal.avif 100w", jpeg="https://example.com/modal.jpeg 100w"
            ),
            sizes="100vw",
            width=100,
            height=100,
        ),
        thumbnail=SimpleNamespace(
            src=SimpleNamespace(jpeg="https://example.com/thumb.jpeg"),
            srcset=SimpleNamespace(
                avif="https://example.com/thumb.avif 50w", jpeg="https://example.com/thumb.jpeg 50w"
            ),
            sizes="50vw",
            width=50,
            height=50,
        ),
    )
    html = get_template("cast/gallery.html").render({"block": SimpleNamespace(id="fallback"), "images": [image]})

    assert "<image-gallery-bs4" in html
    assert "</image-gallery-bs4>" in html


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


def test_get_srcset_images_for_slots_fallback_uses_renditions(monkeypatch):
    slot = renditions.Rectangle(Width(100), Height(100))

    class StubFilters:
        def __init__(self):
            self.original_format = "jpeg"
            self.image_formats = ["jpeg", "webp", "png"]
            self.slots = [slot]
            self.slot_to_fitting_width = {slot: Width(100)}

        def set_filter_to_url_via_wagtail_renditions(self, _renditions):
            return None

        def get_image_for_slot(self, _slot):
            raise ValueError("no fitting image")

    monkeypatch.setattr(
        renditions.RenditionFilters,
        "from_wagtail_image_with_type",
        classmethod(lambda _cls, *_args, **_kwargs: StubFilters()),
    )

    renditions_map = {
        "format-webp": SimpleNamespace(url="https://example.com/test.webp", width=Width(120)),
    }
    images_for_slots = get_srcset_images_for_slots(
        cast(AbstractImage, Stub1PxImage()),
        "gallery",
        renditions=renditions_map,
    )
    image_for_slot = images_for_slots[slot]
    assert image_for_slot.src["webp"] == "https://example.com/test.webp"
    assert image_for_slot.srcset["webp"] == "https://example.com/test.webp 120w"


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


def test_gallery_block_with_layout_get_template_plain_htmx():
    block = GalleryBlockWithLayout()
    template = block.get_template({"layout": "htmx"}, context={"template_base_dir": "plain"})
    assert template == "cast/plain/gallery_htmx.html"


def test_gallery_block_with_layout_get_template_plain_default():
    block = GalleryBlockWithLayout()
    template = block.get_template({"layout": "default"}, context={"template_base_dir": "plain"})
    assert template == "cast/plain/gallery.html"


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


def test_prepare_context_for_gallery_sets_prev_next(monkeypatch):
    class Image:
        def __init__(self, pk: int):
            self.pk = pk

    images = [Image(1), Image(2), Image(3)]
    context: dict = {}

    def fake_add_image_thumbnails(_images, *, context):
        return None

    monkeypatch.setattr("cast.blocks.add_image_thumbnails", fake_add_image_thumbnails)
    result = prepare_context_for_gallery(images, context)

    assert result["image_pks"] == "1,2,3"
    assert [image.pk for image in result["images"]] == [1, 2, 3]
    assert result["images"][0].prev == ""
    assert result["images"][0].next == "gallery-2"
    assert result["images"][1].prev == "gallery-1"
    assert result["images"][1].next == "gallery-3"
    assert result["images"][2].prev == "gallery-2"
    assert result["images"][2].next == ""


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


@pytest.mark.django_db
def test_image_chooser_block_get_context_fallback_to_database(image, monkeypatch):
    monkeypatch.setattr(renditions, "DEFAULT_IMAGE_FORMATS", ("jpeg",))
    cicb = CastImageChooserBlock()
    repository = EmptyRepository()
    context = cicb.get_context(image.pk, parent_context={"repository": repository})
    assert context["value"] == image
    assert context["value"].regular.src["jpeg"]


@pytest.mark.django_db
def test_gallery_image_chooser_block_searchable_content(image):
    block = GalleryImageChooserBlock()
    assert block.get_searchable_content(image) == [image.default_alt_text]
    assert block.get_searchable_content({"value": image}) == [image.default_alt_text]


@pytest.mark.django_db
def test_gallery_image_chooser_block_searchable_content_empty():
    block = GalleryImageChooserBlock()
    assert block.get_searchable_content(None) == []


@pytest.mark.django_db
def test_cast_image_chooser_block_searchable_content_empty():
    block = CastImageChooserBlock()
    assert block.get_searchable_content(None) == []
