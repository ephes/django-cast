import pytest

from cast.content.media_refs import _media_ref_is_available, get_choosable_image


def test_media_reference_resolution_requires_a_user():
    with pytest.raises(TypeError, match="user is required to resolve media refs"):
        get_choosable_image(1, None)


@pytest.mark.parametrize(
    ("block_type", "patch_target"),
    [
        ("image", "cast.content.media_refs.get_choosable_image"),
        ("audio", "cast.content.media_refs.get_choosable_audio"),
        ("video", "cast.content.media_refs.get_choosable_video"),
    ],
)
def test_media_availability_dispatches_to_the_matching_chooser(mocker, block_type, patch_target):
    checker = mocker.patch(patch_target, return_value=object())

    assert _media_ref_is_available(block_type, 7, "user")
    checker.assert_called_once_with(7, "user")


def test_unknown_media_availability_type_is_invalid():
    with pytest.raises(ValueError, match="Unsupported media block type"):
        _media_ref_is_available("unknown", 1, object())
