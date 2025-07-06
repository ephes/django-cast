import pytest
from wagtail.images.models import Image

from cast.blocks import add_prev_next


class TestGalleryDuplicateImages:
    """#171 Test that galleries handle duplicate images correctly."""

    pytestmark = pytest.mark.django_db

    def test_add_prev_next_with_duplicates(self):
        """#171 Test that add_prev_next works with duplicate images using PK-based navigation."""
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
        img = Image()
        img.pk = 1
        images = [img]

        add_prev_next(images)

        assert images[0].prev == "false"
        assert images[0].next == "false"

    def test_add_prev_next_empty_list(self):
        """#171 Test that add_prev_next handles empty list gracefully."""
        images = []

        # Should not raise any exceptions
        add_prev_next(images)

        assert len(images) == 0

    def test_add_prev_next_all_same_pk(self):
        """#171 Test edge case where all images have the same PK."""
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
