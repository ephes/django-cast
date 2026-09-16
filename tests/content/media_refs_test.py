import pytest

from cast.content.media_refs import get_choosable_image


def test_media_reference_resolution_requires_a_user():
    with pytest.raises(TypeError, match="user is required to resolve media refs"):
        get_choosable_image(1, None)
