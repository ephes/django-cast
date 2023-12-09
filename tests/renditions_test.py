import pytest

from cast.renditions import (
    Height,
    ImageFormat,
    Rectangle,
    RenditionFilter,
    RenditionFilters,
    Width,
    calculate_fitting_width,
    get_image_format_by_name,
    get_rendition_filters_for_image_and_slot,
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
    filters_dict = RenditionFilters.build_filters(image, slots, image_formats=["avif", "jpeg"])
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
