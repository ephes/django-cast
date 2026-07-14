import pytest
from django.test import override_settings

from cast.renditions import (
    DEFAULT_IMAGE_FORMATS,
    IMAGE_TYPE_TO_SLOTS,
    FormatRenditionFilter,
    Height,
    ImageFormat,
    Rectangle,
    RenditionFilter,
    RenditionFilters,
    Width,
    calculate_fitting_width,
    get_image_format_by_name,
    get_rendition_filters_for_image_and_slot,
    get_srgb_counterpart_filter_spec,
)

rect = Rectangle
w1, w53, w106, w120, w159, w1110, w4000, w6000, w8000 = (
    Width(x) for x in [1, 53, 106, 120, 159, 1110, 4000, 6000, 8000]
)
h1, h80, h740, h4000, h6000 = Height(1), Height(80), Height(740), Height(4000), Height(6000)
thumbnail_slot = rect(w120, h80)


def test_rectangle_is_equal():
    assert rect(w1, h1) == rect(w1, h1)
    assert rect(w1, h1) != rect(w1, h80)
    with pytest.raises(ValueError):
        rect(w1, h1) == "foo"  # noqa


@pytest.mark.parametrize(
    "width, slot, image_format, original_format, expected_filter_str",
    [
        (w53, rect(w120, h80), "jpeg", "jpeg", "width-53"),
        (w53, rect(w120, h80), "jpeg", "avif", "width-53|format-jpeg"),
        (w53, rect(w120, h80), "avif", "jpeg", "width-53|format-avif"),
    ],
)
def test_get_wagtail_filter_str(
    width, slot, image_format: ImageFormat, original_format: ImageFormat, expected_filter_str
):
    rendition_filter = RenditionFilter(width=width, slot=slot, format=image_format)
    assert rendition_filter.get_wagtail_filter_str(original_format) == expected_filter_str


def test_get_wagtail_filter_str_includes_srgb_before_format_conversion():
    rendition_filter = RenditionFilter(width=w53, slot=thumbnail_slot, format="avif", normalize_to_srgb=True)

    assert rendition_filter.get_wagtail_filter_str("jpeg") == "width-53|srgb|format-avif"


def test_format_rendition_filter_includes_srgb_before_format_conversion():
    rendition_filter = FormatRenditionFilter(
        width=w53,
        slot=thumbnail_slot,
        format="avif",
        normalize_to_srgb=True,
    )

    assert rendition_filter.get_wagtail_filter_str("jpeg") == "srgb|format-avif"


@pytest.mark.parametrize(
    "image, slot, scaled_width",
    [
        (rect(w6000, h4000), rect(w120, h80), 120),  # 3:2 landscape
        (rect(w8000, h4000), rect(w120, h80), 120),  # 2:1 landscape
        (rect(w4000, h6000), rect(w120, h80), 53),  # 2:3 portrait
        (rect(w4000, h4000), rect(w120, h80), 80),  # 1:1 square
    ],
)
def test_calculate_fitting_width(image, slot, scaled_width):
    assert round(calculate_fitting_width(image, slot)) == scaled_width


@pytest.mark.parametrize(
    "image, slot, image_format, max_scale_factor, expected_rendition_filters",
    [
        (rect(w1, h1), rect(w120, h80), "jpeg", 3, []),  # dummy image is too small -> no rendition_filters
        (rect(w1, h1), rect(w120, h80), "avif", 3, []),  # 60 is nearly as big as 53 -> no rendition_filters
        (
            rect(w4000, h6000),
            rect(w120, h80),
            "jpeg",
            3,
            [
                RenditionFilter(width=w53, slot=rect(w120, h80), format="jpeg"),
                RenditionFilter(width=w106, slot=rect(w120, h80), format="jpeg"),
                RenditionFilter(width=w159, slot=rect(w120, h80), format="jpeg"),
            ],
        ),  # 2:3 portrait generates 3 renditions with max_scale_factor=3 because 53*3 < 4000*0.8
    ],
)
def test_get_rendition_filters_for_image_and_slot(
    image, slot, image_format: ImageFormat, max_scale_factor, expected_rendition_filters
):
    rendition_filters = get_rendition_filters_for_image_and_slot(
        image, slot, image_format, max_scale_factor=max_scale_factor
    )
    assert rendition_filters == expected_rendition_filters


@pytest.mark.parametrize(
    "image_name, expected_image_format",
    [
        ("foo.jpg", "jpeg"),
        ("bar.jpeg", "jpeg"),
        ("foo/baz.png", "png"),
        ("an/s/v/g.svg", "svg"),
        ("image.WEBP", "webp"),
        (" image.avif ", "avif"),
    ],
)
def test_get_image_format_by_name(image_name, expected_image_format):
    assert get_image_format_by_name(image_name) == expected_image_format


def test_get_image_format_by_name_not_supported():
    with pytest.raises(ValueError):
        get_image_format_by_name("foo.bmp")


def test_rendition_filters_build_filters():
    # Given a 2:3 portrait image and a thumbnail and a modal image slot
    slots = [
        rect(w120, h80),  # thumbnail
        rect(w1110, h740),  # modal image
    ]
    image = rect(w4000, h6000)  # 2:3 portrait
    # When we get the filters for the image
    rendition_filters = RenditionFilters(
        image=image, slots=slots, image_formats=["avif", "jpeg"], original_format="jpeg"
    )
    filters_dict = rendition_filters.build_filters()
    filters = RenditionFilters.get_all_filters(filters_dict)
    # Then we get 3 filters for the thumbnail and 3 filters for the modal image
    widths = sorted({f.width for f in filters})
    assert widths == [53, 106, 159, 493, 986, 1479]


def test_rendition_filters_get_filter_by_slot_format_and_fitting_width():
    # Given an empty list of rendition filters
    image_1px = rect(w1, h1)
    [slot] = slots = [Rectangle(w120, h80)]
    rendition_filters = RenditionFilters(
        image=image_1px, original_format="jpeg", slots=slots, image_formats=["avif", "jpeg"]
    )
    # When we try to get a filter by format and width
    with pytest.raises(ValueError):
        # Then we get a ValueError
        rendition_filters.get_filter_by_slot_format_and_fitting_width(slot, "jpeg", w53)

    # Given a list of rendition filters containing a filter for jpeg and width 53
    expected_filter = RenditionFilter(width=w53, slot=thumbnail_slot, format="jpeg")
    rendition_filters.filters[slot]["jpeg"] = [expected_filter]
    # When we get a filter by format and width
    actual_filter = rendition_filters.get_filter_by_slot_format_and_fitting_width(slot, "jpeg", w53)
    # Then we get the expected filter
    assert actual_filter == expected_filter

    # Given there are two filters for jpeg and width 53 and 106
    rendition_filters.filters[slot]["jpeg"] = [expected_filter, expected_filter]
    # When we get a filter by format and width
    with pytest.raises(ValueError):
        # Then we get a ValueError
        rendition_filters.get_filter_by_slot_format_and_fitting_width(slot, "jpeg", w53)


class StubWagtailImage:
    class File:
        name = "test.jpg"

    width = 6000
    height = 4000
    file = File()


def test_rendition_filters_from_wagtail_image_with_type_respects_override_settings():
    with override_settings(
        CAST_REGULAR_IMAGE_SLOT_DIMENSIONS=[(200, 100)],
        CAST_IMAGE_FORMATS=["webp"],
    ):
        filters = RenditionFilters.from_wagtail_image_with_type(StubWagtailImage(), "regular")

    assert filters.slots == [Rectangle(Width(200), Height(100))]
    assert list(filters.image_formats) == ["webp"]


def test_gallery_thumbnail_rendition_filters_normalize_to_srgb_by_default():
    with override_settings(
        CAST_GALLERY_IMAGE_SLOT_DIMENSIONS=[(1110, 740), (120, 80)],
        CAST_IMAGE_FORMATS=["jpeg", "avif"],
    ):
        filters = RenditionFilters.from_wagtail_image_with_type(StubWagtailImage(), "gallery")

    assert "width-120" not in filters.filter_strings
    assert "width-120|format-avif" not in filters.filter_strings
    assert "width-120|srgb" in filters.filter_strings
    assert "width-120|srgb|format-avif" in filters.filter_strings
    assert "width-1110" in filters.filter_strings
    assert "width-1110|format-avif" in filters.filter_strings
    assert "width-1110|srgb" not in filters.filter_strings
    assert "width-1110|srgb|format-avif" not in filters.filter_strings


def test_gallery_thumbnail_srgb_normalization_can_be_disabled():
    with override_settings(
        CAST_GALLERY_IMAGE_SLOT_DIMENSIONS=[(1110, 740), (120, 80)],
        CAST_IMAGE_FORMATS=["jpeg", "avif"],
        CAST_GALLERY_THUMBNAIL_RENDITIONS_SRGB=False,
    ):
        filters = RenditionFilters.from_wagtail_image_with_type(StubWagtailImage(), "gallery")

    assert "width-120" in filters.filter_strings
    assert "width-120|format-avif" in filters.filter_strings
    assert "width-120|srgb" not in filters.filter_strings
    assert "width-120|srgb|format-avif" not in filters.filter_strings


def test_image_type_to_slots_is_runtime_mapping():
    with override_settings(
        CAST_REGULAR_IMAGE_SLOT_DIMENSIONS=[(200, 100)],
        CAST_GALLERY_IMAGE_SLOT_DIMENSIONS=[(300, 200), (120, 80)],
    ):
        assert len(IMAGE_TYPE_TO_SLOTS) == 2
        assert list(IMAGE_TYPE_TO_SLOTS) == ["regular", "gallery"]
        assert IMAGE_TYPE_TO_SLOTS["regular"] == [Rectangle(Width(200), Height(100))]


def test_default_image_formats_is_runtime_sequence():
    with override_settings(CAST_IMAGE_FORMATS=["webp", "jpeg"]):
        assert len(DEFAULT_IMAGE_FORMATS) == 2
        assert list(DEFAULT_IMAGE_FORMATS) == ["webp", "jpeg"]
        assert DEFAULT_IMAGE_FORMATS[0] == "webp"
        assert list(DEFAULT_IMAGE_FORMATS[:1]) == ["webp"]


class RenditionStub:
    def __init__(self, url):
        self.url = url


def test_gallery_thumbnail_uses_existing_pre_srgb_renditions_until_sync():
    with override_settings(
        CAST_GALLERY_IMAGE_SLOT_DIMENSIONS=[(1110, 740), (120, 80)],
        CAST_IMAGE_FORMATS=["jpeg", "avif"],
    ):
        rendition_filters = RenditionFilters.from_wagtail_image_with_type(StubWagtailImage(), "gallery")

    rendition_filters.set_filter_to_url_via_wagtail_renditions(
        {
            "width-120": RenditionStub("/legacy-120.jpg"),
            "width-240": RenditionStub("/legacy-240.jpg"),
            "width-360": RenditionStub("/legacy-360.jpg"),
            "width-120|format-avif": RenditionStub("/legacy-120.avif"),
            "width-240|format-avif": RenditionStub("/legacy-240.avif"),
            "width-360|format-avif": RenditionStub("/legacy-360.avif"),
        }
    )

    thumbnail = rendition_filters.get_image_for_slot(rendition_filters.slots[1])

    assert thumbnail.src == {"jpeg": "/legacy-120.jpg", "avif": "/legacy-120.avif"}
    assert thumbnail.srcset == {
        "jpeg": "/legacy-120.jpg 120w, /legacy-240.jpg 240w, /legacy-360.jpg 360w",
        "avif": "/legacy-120.avif 120w, /legacy-240.avif 240w, /legacy-360.avif 360w",
    }


def test_gallery_thumbnail_uses_existing_srgb_renditions_when_policy_is_disabled():
    with override_settings(
        CAST_GALLERY_IMAGE_SLOT_DIMENSIONS=[(1110, 740), (120, 80)],
        CAST_IMAGE_FORMATS=["jpeg"],
        CAST_GALLERY_THUMBNAIL_RENDITIONS_SRGB=False,
    ):
        rendition_filters = RenditionFilters.from_wagtail_image_with_type(StubWagtailImage(), "gallery")

    rendition_filters.set_filter_to_url_via_wagtail_renditions(
        {
            "width-120|srgb": RenditionStub("/srgb-120.jpg"),
            "width-240|srgb": RenditionStub("/srgb-240.jpg"),
            "width-360|srgb": RenditionStub("/srgb-360.jpg"),
        }
    )

    thumbnail = rendition_filters.get_image_for_slot(rendition_filters.slots[1])

    assert thumbnail.src == {"jpeg": "/srgb-120.jpg"}
    assert thumbnail.srcset == {"jpeg": "/srgb-120.jpg 120w, /srgb-240.jpg 240w, /srgb-360.jpg 360w"}


def test_srcset_keeps_width_matched_to_each_available_rendition():
    rendition_filters = RenditionFilters(
        image=Rectangle(Width(4000), Height(6000)),
        original_format="jpeg",
        slots=[thumbnail_slot],
        image_formats=["jpeg"],
    )
    rendition_filters.set_filter_to_url_via_wagtail_renditions({"width-106": RenditionStub("/available-106.jpg")})

    thumbnail = rendition_filters.get_image_for_slot(thumbnail_slot)

    assert thumbnail.src == {}
    assert thumbnail.srcset == {"jpeg": "/available-106.jpg 106w"}


@pytest.mark.parametrize(
    ("filter_spec", "expected"),
    [
        ("width-120", "width-120|srgb"),
        ("width-120|format-avif", "width-120|srgb|format-avif"),
        ("width-120|srgb", "width-120"),
        ("width-120|srgb|format-avif", "width-120|format-avif"),
        ("format-avif", "srgb|format-avif"),
        ("srgb|format-avif", "format-avif"),
        ("max-165x165", None),
        ("fill-1x1", None),
    ],
)
def test_get_srgb_counterpart_filter_spec(filter_spec, expected):
    assert get_srgb_counterpart_filter_spec(filter_spec) == expected


# def test_get_renditions_to_fetch():
#     # Given a list of renditions and a list of filters
#     [slot] = slots = IMAGE_TYPE_TO_SLOTS["regular"]
#     image = Rectangle(w6000, h4000)
#     rendition_filters = RenditionFilters(
#         image=image, original_format="png", slots=slots, image_formats=["avif", "jpeg"])
#     renditions = {}
#     for filter_string in rendition_filters.filter_strings:
#         width = filter_string.split("|")[0].split("-")[-1]
#         image_format = filter_string.split("|")[-1].split("-")[-1]
#         renditions[filter_string] = RenditionStub(f"foobar-{width}.{image_format}")
#     rendition_filters.set_filter_to_url_via_wagtail_renditions(renditions)
#     print(rendition_filters.filter_strings)
#     image_for_slot = rendition_filters.get_image_for_slot(slot)
#     print(image_for_slot)
#     # print(rendition_filters.filter_to_url)
#     # When we get the renditions to fetch
#     # Then we get the expected renditions to fetch
#     assert False
