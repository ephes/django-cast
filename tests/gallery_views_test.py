from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory
from django.urls import reverse
import pytest
from wagtail.images.models import Image

from cast.views.gallery import GalleryModalForm, gallery_modal, get_prev_next_indices


@pytest.fixture
def gallery_duplicate_images(image_1px):
    image1 = Image(file=image_1px, title="Image 1")
    image1.save()

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

    return image1, image2


def test_gallery_modal_form_happy():
    """#171 Test happy path for gallery modal form."""
    data = {"current_image_index": 0, "image_pks": "1,2,3", "block_id": "block_id"}
    form = GalleryModalForm(data)
    assert form.is_valid()
    assert form.cleaned_data["image_pks"] == [1, 2, 3]


def test_gallery_modal_form_current_image_not_in_gallery():
    """#171 Test form validation when current image index is out of range."""
    data = {"current_image_index": 3, "image_pks": "1,2,3", "block_id": "block_id"}
    form = GalleryModalForm(data)
    assert not form.is_valid()
    assert "current_image_index 3 is out of range for image_pks with length 3" in str(form.errors)


def test_gallery_modal_form_current_image_index_required():
    """#171 Test that current_image_index is required."""
    data = {"image_pks": "1,2,3", "block_id": "block_id"}
    form = GalleryModalForm(data)
    assert not form.is_valid()
    assert form.errors["current_image_index"][0] == "This field is required."


def test_gallery_modal_form_image_pks_empty():
    """#171 Test form with empty image_pks."""
    data = {"current_image_pk": 4, "image_pks": "", "block_id": "block_id"}
    form = GalleryModalForm(data)
    assert not form.is_valid()
    assert form.errors["image_pks"][0] == "This field is required."


def test_gallery_modal_form_malicious_input():
    """#171 Test form handles malicious input safely."""
    data = {"current_image_pk": 4, "image_pks": "1,2,3,if(now()=sysdate()", "block_id": "block_id"}
    form = GalleryModalForm(data)
    assert not form.is_valid()
    assert form.errors["image_pks"][0] == "Enter a list of image ids."


@pytest.mark.parametrize(
    "current_image_pk,image_pks,expected_prev_next",
    [
        (1, [1], (None, None)),
        (1, [1, 2], (None, 2)),
        (1, [1, 2, 3], (None, 2)),
        (2, [1, 2, 3], (1, 3)),
        (3, [1, 2, 3], (2, None)),
    ],
)
def test_get_prev_next_indices(current_image_pk, image_pks, expected_prev_next):
    """#171 Test get_prev_next_indices function with various inputs."""
    # Convert current_image_pk to index
    current_index = image_pks.index(current_image_pk)
    prev_index, next_index = get_prev_next_indices(image_pks, current_index)
    # Convert indices back to PKs
    prev_pk = image_pks[prev_index] if prev_index is not None else None
    next_pk = image_pks[next_index] if next_index is not None else None
    prev_next = (prev_pk, next_pk)
    assert prev_next == expected_prev_next


@pytest.mark.django_db
def test_htmx_gallery_modal_happy(client, gallery):
    """#171 Test successful HTMX gallery modal request."""
    gallery.create_renditions()
    image_pks = ",".join([str(image.pk) for image in gallery.images.all()])
    current_image_index = 0
    block_id = "block_id"
    base_url = reverse("cast:gallery-modal", kwargs={"template_base_dir": "plain"})
    url = f"{base_url}?current_image_index={current_image_index}&image_pks={image_pks}&block_id={block_id}"
    response = client.get(url)
    assert response.status_code == 200


def test_htmx_gallery_modal_without_current_image_index_invalid(client):
    """#171 Test HTMX request without current_image_index returns 400."""
    image_pks = "1,2,3"
    block_id = "block_id"
    base_url = reverse("cast:gallery-modal", kwargs={"template_base_dir": "plain"})
    url = f"{base_url}?&image_pks={image_pks}&block_id={block_id}"
    response = client.get(url)
    assert response.status_code == 400


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

    def test_gallery_modal_with_duplicate_images(self, gallery_duplicate_images):
        """#171 Test gallery_modal view handles duplicate images correctly."""
        image1, image2 = gallery_duplicate_images
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

    def test_gallery_modal_duplicate_prev_next_indices(self, client, gallery_duplicate_images):
        """#171 Ensure duplicate prev/next indices are preserved in modal context."""
        image1, image2 = gallery_duplicate_images
        image_pks = [image1.pk, image2.pk, image1.pk, image2.pk, image1.pk]
        current_image_index = 2
        block_id = "test-block"

        base_url = reverse("cast:gallery-modal", kwargs={"template_base_dir": "bootstrap4"})
        url = f"{base_url}?current_image_index={current_image_index}&image_pks={','.join(map(str, image_pks))}&block_id={block_id}"
        response = client.get(url)

        assert response.status_code == 200
        assert response.context is not None
        prev_image = response.context["prev_image"]
        next_image = response.context["next_image"]
        assert prev_image.gallery_index == 1
        assert next_image.gallery_index == 3
        assert prev_image.pk == image2.pk
        assert next_image.pk == image2.pk

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
