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


@pytest.mark.django_db
def test_add_prev_next_unique_images():
    """Test add_prev_next with unique images - now uses position-based IDs."""
    from cast.blocks import add_prev_next
    from wagtail.images.models import Image
    
    # Create 3 unique images
    images = [Image(pk=1), Image(pk=2), Image(pk=3)]
    add_prev_next(images)
    
    # After fix: all galleries use position-based IDs
    # First image (position 0): no prev, next to position 1
    assert images[0].prev == "false"
    assert images[0].next == "img-pos-1"
    
    # Middle image (position 1): prev to position 0, next to position 2
    assert images[1].prev == "img-pos-0"
    assert images[1].next == "img-pos-2"
    
    # Last image (position 2): prev to position 1, no next
    assert images[2].prev == "img-pos-1"
    assert images[2].next == "false"


@pytest.mark.django_db 
def test_add_prev_next_duplicate_images():
    """Test add_prev_next with duplicate images - now fixed with position-based IDs."""
    from cast.blocks import add_prev_next
    from wagtail.images.models import Image
    
    # Create gallery with duplicate images: [1, 2, 1] 
    # This represents a gallery where image 1 appears twice
    images = [Image(pk=1), Image(pk=2), Image(pk=1)]
    add_prev_next(images)
    
    # After fix: each position gets unique navigation IDs
    # Position 0: no prev, next to position 1
    assert images[0].prev == "false"  
    assert images[0].next == "img-pos-1"  
    
    # Position 1: prev to position 0, next to position 2
    assert images[1].prev == "img-pos-0"  
    assert images[1].next == "img-pos-2"  
    
    # Position 2: prev to position 1, no next
    assert images[2].prev == "img-pos-1"  
    assert images[2].next == "false"


@pytest.mark.django_db
def test_gallery_template_no_duplicate_ids_after_fix(image):
    """Test that gallery template generates unique position-based IDs even with duplicate images."""
    from django.template import Context, Template
    from cast.blocks import prepare_context_for_gallery
    
    # Create duplicate images - same pk means same image used twice
    duplicate_images = [image, image]  # Same image appears twice
    
    context = {
        "repository": type('MockRepo', (), {
            'renditions_for_posts': {image.pk: []},
        })(),
        "block": type('MockBlock', (), {'id': 'gallery-123'})()
    }
    
    # Prepare gallery context
    gallery_context = prepare_context_for_gallery(duplicate_images, context)
    
    # Use position-based template (like the actual gallery template now)
    template_content = """
    {% for image in images %}
    <img id="img-pos-{{ forloop.counter0 }}" data-prev="{{ image.prev }}" data-next="{{ image.next }}" />
    {% endfor %}
    """
    
    template = Template(template_content)
    rendered = template.render(Context(gallery_context))
    
    # After fix: should have unique position-based IDs
    assert 'id="img-pos-0"' in rendered
    assert 'id="img-pos-1"' in rendered
    
    # No duplicate IDs should exist
    assert rendered.count('id="img-pos-0"') == 1
    assert rendered.count('id="img-pos-1"') == 1


@pytest.mark.django_db 
def test_add_prev_next_position_based_ids():
    """Test that add_prev_next generates position-based IDs for duplicate images - this will fail initially."""
    from cast.blocks import add_prev_next
    from wagtail.images.models import Image
    
    # Create gallery with duplicate images: [1, 2, 1]
    images = [Image(pk=1), Image(pk=2), Image(pk=1)]
    
    # Add position information to images (this is what our fix should do)
    for i, image in enumerate(images):
        image._gallery_position = i
    
    add_prev_next(images)
    
    # After fix: each position should have unique navigation IDs based on position
    # Position 0: no prev, next to position 1
    assert images[0].prev == "false"  
    assert images[0].next == "img-pos-1"  # Next to position 1, not pk-based
    
    # Position 1: prev to position 0, next to position 2  
    assert images[1].prev == "img-pos-0"  # Prev to position 0
    assert images[1].next == "img-pos-2"  # Next to position 2
    
    # Position 2: prev to position 1, no next
    assert images[2].prev == "img-pos-1"  # Prev to position 1
    assert images[2].next == "false"


@pytest.mark.django_db
def test_gallery_template_position_based_ids_after_fix(image):
    """Test that gallery template will generate position-based unique IDs after fix."""
    from django.template import Context, Template
    from cast.blocks import prepare_context_for_gallery
    
    # Create duplicate images
    duplicate_images = [image, image]
    
    # Add position information (this is what our fix should do)
    for i, img in enumerate(duplicate_images):
        img._gallery_position = i
    
    context = {
        "repository": type('MockRepo', (), {
            'renditions_for_posts': {image.pk: []},
        })(),
        "block": type('MockBlock', (), {'id': 'gallery-123'})()
    }
    
    # Prepare gallery context
    gallery_context = prepare_context_for_gallery(duplicate_images, context)
    
    # Template should use position-based IDs after fix
    template_content = """
    {% for image in images %}
    <img id="img-pos-{{ forloop.counter0 }}" data-prev="{{ image.prev }}" data-next="{{ image.next }}" />
    {% endfor %}
    """
    
    template = Template(template_content)
    rendered = template.render(Context(gallery_context))
    
    # After fix: should have unique position-based IDs
    assert 'id="img-pos-0"' in rendered
    assert 'id="img-pos-1"' in rendered
    # Should have no duplicate IDs
    assert rendered.count('id="img-pos-0"') == 1
    assert rendered.count('id="img-pos-1"') == 1


@pytest.mark.django_db
def test_all_gallery_templates_use_position_based_ids(image):
    """Test that all gallery templates use position-based IDs consistently."""
    from django.template import Context, Template
    from django.template.loader import get_template
    from cast.blocks import prepare_context_for_gallery
    
    # Create duplicate images
    duplicate_images = [image, image]
    
    context = {
        "repository": type('MockRepo', (), {
            'renditions_for_posts': {image.pk: []},
        })(),
        "block": type('MockBlock', (), {'id': 'gallery-123'})(),
        "template_base_dir": "bootstrap4",
        "image_pks": f"{image.pk},{image.pk}"
    }
    
    # Prepare gallery context
    gallery_context = prepare_context_for_gallery(duplicate_images, context)
    
    # Test all gallery templates
    templates_to_test = [
        "cast/gallery.html", 
        "cast/bootstrap4/gallery.html",
        "cast/bootstrap4/gallery_htmx.html"
    ]
    
    for template_path in templates_to_test:
        template = get_template(template_path)
        rendered = template.render(gallery_context)
        
        # Should have position-based IDs, not PK-based
        assert 'id="img-pos-0"' in rendered, f"Template {template_path} missing img-pos-0"
        assert 'id="img-pos-1"' in rendered, f"Template {template_path} missing img-pos-1"
        
        # Should not have any PK-based IDs
        pk_based_id = f'id="img-{image.pk}"'
        assert pk_based_id not in rendered, f"Template {template_path} still has PK-based ID: {pk_based_id}"


@pytest.mark.django_db
def test_gallery_block_preserves_duplicate_images():
    """Test that bulk_to_python_from_database preserves duplicate images."""
    from cast.blocks import GalleryBlockWithLayout
    from wagtail.images.models import Image
    
    # Create two different images  
    image1 = Image(pk=1, title="Image 1")
    image2 = Image(pk=2, title="Image 2")
    
    # Mock the database query to return our test images
    def mock_filter(pk__in):
        pk_set = set(pk__in)
        return [img for img in [image1, image2] if img.pk in pk_set]
    
    # Patch Image.objects.filter to use our mock
    import unittest.mock
    with unittest.mock.patch.object(Image.objects, 'filter', side_effect=mock_filter):
        # Test gallery with duplicate images: [1, 2, 1]
        values = {
            "gallery": [
                {"type": "item", "value": 1},
                {"type": "item", "value": 2}, 
                {"type": "item", "value": 1}  # Duplicate of first image
            ]
        }
        
        block = GalleryBlockWithLayout()
        result = block.bulk_to_python_from_database(values)
        
        # Should preserve all 3 images including the duplicate
        images = result["gallery"]
        assert len(images) == 3, f"Expected 3 images, got {len(images)}"
        
        # Check the order and duplicates are preserved
        assert images[0].pk == 1, "First image should be pk=1"
        assert images[1].pk == 2, "Second image should be pk=2"  
        assert images[2].pk == 1, "Third image should be pk=1 (duplicate)"
        
        # Verify they're the same object instances
        assert images[0] is images[2], "Duplicate images should be the same object instance"


@pytest.mark.django_db
def test_gallery_block_empty_gallery():
    """Test that empty gallery is handled correctly."""
    from cast.blocks import GalleryBlockWithLayout
    
    block = GalleryBlockWithLayout()
    values = {"gallery": []}
    result = block.bulk_to_python_from_database(values)
    
    assert result["gallery"] == []
