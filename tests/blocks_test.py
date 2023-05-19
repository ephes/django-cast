import pytest
from wagtail.images.blocks import ImageChooserBlock

from cast.blocks import CodeBlock, GalleryBlock


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
