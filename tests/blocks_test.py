import pytest
from wagtail.images.blocks import ImageChooserBlock

from cast.blocks import CodeBlock, GalleryBlock, Thumbnail, calculate_thumbnail_width


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, ""),  # make sure None is rendered as empty string
        (  # make sure source is rendered even if language is not found
            {"language": "nonexistent", "source": "blub"},
            ('<div class="highlight"><pre><span></span>blub\n' "</pre></div>\n"),
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
    assert block.get_template(context=context) == GalleryBlock.default_template_name


def test_gallery_block_template_from_theme(mocker):
    mocker.patch("cast.blocks.get_template")
    block = GalleryBlock(ImageChooserBlock())
    template_name = block.get_template(context={"template_base_dir": "vue"})
    assert template_name == "cast/vue/gallery.html"


@pytest.mark.parametrize(
    "original_width, original_height, slot_width, slot_height, expected_width",
    [
        (6000, 4000, 120, 80, 120),  # 3:2 landscape
        (8000, 4000, 120, 80, 120),  # 2:1 landscape
        (4000, 6000, 120, 80, 53),  # 2:3 portrait
        (4000, 4000, 120, 80, 80),  # 1:1 square
    ],
)
def test_calculate_thumbnail_width(original_width, original_height, slot_width, slot_height, expected_width):
    assert round(calculate_thumbnail_width(original_width, original_height, slot_width, slot_height)) == expected_width


class StubImage:
    url = "image_url"

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height

    def get_rendition(self, width: str) -> "StubImage":
        return self


def test_thumbnail_attributes():
    image = StubImage(6000, 4000)
    thumbnail = Thumbnail(image, 120, 80, max_scale_factor=1)
    assert thumbnail.src["jpeg"] == image.url
    assert thumbnail.srcset["jpeg"] == f"{image.url} {image.width}w"
    assert thumbnail.sizes == f"{image.width}px"
