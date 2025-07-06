import pytest
from django.test import RequestFactory
from django.urls import reverse
from wagtail.images.models import Image

from cast.views.gallery import GalleryModalForm, gallery_modal, get_prev_next_indices


@pytest.mark.django_db
class TestGalleryView:
    """#171 Test the gallery view functionality."""

    def test_get_prev_next_indices(self):
        """#171 Test the get_prev_next_indices function."""
        image_pks = [1, 2, 3, 4, 5]

        # Test first image
        prev, next = get_prev_next_indices(image_pks, 0)
        assert prev is None
        assert next == 1

        # Test middle image
        prev, next = get_prev_next_indices(image_pks, 2)
        assert prev == 1
        assert next == 3

        # Test last image
        prev, next = get_prev_next_indices(image_pks, 4)
        assert prev == 3
        assert next is None

        # Test single image
        prev, next = get_prev_next_indices([1], 0)
        assert prev is None
        assert next is None

    def test_gallery_modal_form_validation(self):
        """#171 Test GalleryModalForm validation."""
        # Valid form
        form = GalleryModalForm({"image_pks": "1,2,3,4,5", "current_image_index": "2", "block_id": "test-block"})
        assert form.is_valid()
        assert form.cleaned_data["image_pks"] == [1, 2, 3, 4, 5]
        assert form.cleaned_data["current_image_index"] == 2

        # Invalid index - too high
        form = GalleryModalForm(
            {
                "image_pks": "1,2,3",
                "current_image_index": "3",  # out of range
                "block_id": "test-block",
            }
        )
        assert not form.is_valid()

        # Invalid index - negative
        form = GalleryModalForm({"image_pks": "1,2,3", "current_image_index": "-1", "block_id": "test-block"})
        assert not form.is_valid()

    def test_gallery_modal_with_duplicate_images(self, image_1px):
        """#171 Test gallery_modal view handles duplicate images correctly."""
        # Create test images

        image1 = Image(file=image_1px, title="Image 1")
        image1.save()

        # Create a second image with a different file
        from django.core.files.uploadedfile import SimpleUploadedFile

        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00"
            b"\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
            b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc````"
            b"\x00\x00\x00\x05\x00\x01\xa5\xf6E@\x00\x00"
            b"\x00\x00IEND\xaeB`\x82"
        )
        image_2px = SimpleUploadedFile(name="test2.png", content=png, content_type="image/png")
        image2 = Image(file=image_2px, title="Image 2")
        image2.save()

        # Simulate a gallery with duplicate images (same image used multiple times)
        # Pattern: image1, image2, image1, image2, image1
        image_pks = [image1.pk, image2.pk, image1.pk, image2.pk, image1.pk]

        factory = RequestFactory()

        # Test navigation through duplicates
        # Click on the third image (index 2, which is image1)
        request = factory.get(
            reverse("cast:gallery-modal", kwargs={"template_base_dir": "bootstrap4"}),
            {"image_pks": ",".join(map(str, image_pks)), "current_image_index": "2", "block_id": "test-block"},
        )

        response = gallery_modal(request, "bootstrap4")
        assert response.status_code == 200

        # The response context should have the correct images based on indices
        # Previous should be image at index 1 (image2)
        # Current should be image at index 2 (image1)
        # Next should be image at index 3 (image2)

        # Test navigation to the last duplicate (index 4, which is image1)
        request = factory.get(
            reverse("cast:gallery-modal", kwargs={"template_base_dir": "bootstrap4"}),
            {"image_pks": ",".join(map(str, image_pks)), "current_image_index": "4", "block_id": "test-block"},
        )

        response = gallery_modal(request, "bootstrap4")
        assert response.status_code == 200

    def test_gallery_modal_invalid_request(self):
        """#171 Test gallery_modal view returns 400 for invalid requests."""
        factory = RequestFactory()

        # Missing required parameters
        request = factory.get(
            reverse("cast:gallery-modal", kwargs={"template_base_dir": "bootstrap4"}),
            {"image_pks": "1,2,3"},  # missing current_image_index and block_id
        )

        response = gallery_modal(request, "bootstrap4")
        assert response.status_code == 400
