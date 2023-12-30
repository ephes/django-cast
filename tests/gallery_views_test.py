import pytest
from django.urls import reverse

from cast.views.gallery import GalleryModalForm, get_prev_next_pk


def test_gallery_modal_form_happy():
    data = {"current_image_pk": 1, "image_pks": "1,2,3", "block_id": "block_id"}
    form = GalleryModalForm(data)
    assert form.is_valid()
    assert form.cleaned_data["image_pks"] == [1, 2, 3]


def test_gallery_modal_form_current_image_not_in_gallery():
    data = {"current_image_pk": 4, "image_pks": "1,2,3", "block_id": "block_id"}
    form = GalleryModalForm(data)
    assert not form.is_valid()
    assert list(form.errors["__all__"])[0] == "current_image_pk 4 is not in image_pks [1, 2, 3]"


def test_gallery_modal_form_current_image_pk_required():
    data = {"image_pks": "1,2,3", "block_id": "block_id"}
    form = GalleryModalForm(data)
    assert not form.is_valid()
    assert form.errors["current_image_pk"][0] == "This field is required."


def test_gallery_modal_form_image_pks_empty():
    data = {"current_image_pk": 4, "image_pks": "", "block_id": "block_id"}
    form = GalleryModalForm(data)
    assert not form.is_valid()
    assert form.errors["image_pks"][0] == "This field is required."


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
def test_get_prev_next_pk(current_image_pk, image_pks, expected_prev_next):
    prev_next = get_prev_next_pk(image_pks, current_image_pk)
    assert prev_next == expected_prev_next


@pytest.mark.django_db
def test_htmx_gallery_modal_happy(client, gallery):
    image_pks = ",".join([str(image.pk) for image in gallery.images.all()])
    current_image_pk = image_pks[0]
    block_id = "block_id"
    base_url = reverse("cast:gallery-modal", kwargs={"template_base_dir": "plain"})
    url = f"{base_url}?current_image_pk={current_image_pk}&image_pks={image_pks}&block_id={block_id}"
    response = client.get(url)
    assert response.status_code == 200


def test_htmx_gallery_modal_without_current_image_pk_invalid(client):
    image_pks = "1,2,3"
    block_id = "block_id"
    base_url = reverse("cast:gallery-modal", kwargs={"template_base_dir": "plain"})
    url = f"{base_url}?&image_pks={image_pks}&block_id={block_id}"
    response = client.get(url)
    assert response.status_code == 400
