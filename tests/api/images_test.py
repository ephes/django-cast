import pytest
from django.core.files.base import ContentFile
from django.urls import reverse
from wagtail.images import get_image_model
from wagtail.models import Collection, CollectionViewRestriction


@pytest.mark.django_db
def test_image_api_omits_images_below_restricted_collection(api_client, image):
    root = Collection.get_first_root_node()
    restricted = root.add_child(name="Restricted images")
    nested = restricted.add_child(name="Nested restricted images")
    CollectionViewRestriction.objects.create(
        collection=restricted,
        restriction_type=CollectionViewRestriction.LOGIN,
    )
    with image.file.open("rb") as source:
        private_file = ContentFile(source.read(), name="private-descendant.gif")
    private_image = get_image_model()(
        collection=nested,
        title="Private descendant image",
        file=private_file,
    )
    private_image.save()

    response = api_client.get(reverse("cast:api:wagtail:images:listing"), format="json")

    assert response.status_code == 200
    returned_ids = {item["id"] for item in response.json()["items"]}
    assert image.pk in returned_ids
    assert private_image.pk not in returned_ids
    assert private_image.title not in response.content.decode()
    assert private_image.file.url not in response.content.decode()

    detail_response = api_client.get(
        reverse("cast:api:wagtail:images:detail", kwargs={"pk": private_image.pk}),
        format="json",
    )
    assert detail_response.status_code == 404
    assert private_image.title not in detail_response.content.decode()
    assert private_image.file.url not in detail_response.content.decode()
