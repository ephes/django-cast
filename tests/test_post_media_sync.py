import pytest

from cast.models import sync_media_ids


@pytest.mark.parametrize(
    "source, target, expected_to_add, expected_to_remove",
    [
        # source, target, expected_to_add, expected_to_remove
        ({}, {}, {}, {}),
        ({}, {"video": {1}}, {"video": {1}}, {}),  # add video
        ({"video": {1}}, {}, {}, {"video": {1}}),  # remove video
        ({"video": {1}}, {"video": {2}}, {"video": {2}}, {"video": {1}}),  # add video 2, remove video 1
        # add + remove different media types
        (
            {"audio": {0}, "video": {1}},
            {"video": {2}, "audio": {1}},
            {"audio": {1}, "video": {2}},
            {"video": {1}, "audio": {0}},
        ),
    ],
)
def test_sync_media_ids(source, target, expected_to_add, expected_to_remove):
    assert sync_media_ids(source, target) == (expected_to_add, expected_to_remove)
