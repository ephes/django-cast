import pytest
from django.urls import reverse

from cast.views.gallery import GalleryModalForm, get_prev_next_indices


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
