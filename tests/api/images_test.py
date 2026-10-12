import pytest
from django.core.files.base import ContentFile
from django.urls import reverse
from wagtail.images import get_image_model
from wagtail.models import Collection, CollectionViewRestriction

from cast.api.views import CastImagesAPIViewSet, wagtail_api_router

LISTING = "cast:api:wagtail:images:listing"
DETAIL = "cast:api:wagtail:images:detail"


def _detail_url(image):
    return reverse(DETAIL, kwargs={"pk": image.pk})


def test_images_endpoint_is_still_registered():
    assert wagtail_api_router._endpoints["images"] is CastImagesAPIViewSet
    assert reverse(LISTING).endswith("/api/wagtail/images/")


@pytest.mark.django_db
@pytest.mark.parametrize("url_name", [LISTING, DETAIL, "cast:api:wagtail:images:find"])
def test_anonymous_image_api_is_denied_by_default(api_client, image, url_name):
    if url_name == DETAIL:
        url = _detail_url(image)
    elif url_name == LISTING:
        url = reverse(url_name)
    else:
        url = f"{reverse(url_name)}?id={image.pk}"

    response = api_client.get(url, format="json")

    assert response.status_code in (401, 403)
    body = response.content.decode()
    assert image.title not in body
    assert image.file.url not in body
    assert "no-store" in response["Cache-Control"]
    assert "private" in response["Cache-Control"]


@pytest.mark.django_db
def test_non_staff_user_is_denied_by_default(api_client, user, image):
    api_client.force_authenticate(user=user)

    listing = api_client.get(reverse(LISTING), format="json")
    detail = api_client.get(_detail_url(image), format="json")

    assert listing.status_code == 403
    assert detail.status_code == 403
    assert image.file.url not in listing.content.decode()


@pytest.mark.django_db
def test_inactive_staff_user_is_denied(api_client, admin_user, image):
    admin_user.is_active = False
    api_client.force_authenticate(user=admin_user)

    response = api_client.get(reverse(LISTING), format="json")

    assert response.status_code == 403


@pytest.mark.django_db
def test_staff_user_can_list_and_fetch_images(admin_client, image):
    listing = admin_client.get(reverse(LISTING))
    detail = admin_client.get(_detail_url(image))

    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()["items"]] == [image.pk]
    assert detail.status_code == 200
    assert detail.json()["id"] == image.pk
    assert "no-store" in listing["Cache-Control"]
    assert "private" in listing["Cache-Control"]
    assert "Cookie" in listing["Vary"]
    assert "Authorization" in listing["Vary"]


@pytest.mark.django_db
def test_public_images_api_setting_restores_anonymous_access(api_client, image, settings):
    settings.CAST_PUBLIC_IMAGES_API = True

    listing = api_client.get(reverse(LISTING), format="json")
    detail = api_client.get(_detail_url(image), format="json")

    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()["items"]] == [image.pk]
    assert detail.status_code == 200
    assert "no-store" not in listing.get("Cache-Control", "")


@pytest.mark.django_db
def test_truthy_non_bool_setting_does_not_open_image_api(api_client, image, settings):
    settings.CAST_PUBLIC_IMAGES_API = "False"

    response = api_client.get(reverse(LISTING), format="json")

    assert response.status_code in (401, 403)


@pytest.mark.django_db
def test_image_api_omits_images_below_restricted_collection(api_client, image, settings):
    settings.CAST_PUBLIC_IMAGES_API = True
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

    response = api_client.get(reverse(LISTING), format="json")

    assert response.status_code == 200
    returned_ids = {item["id"] for item in response.json()["items"]}
    assert image.pk in returned_ids
    assert private_image.pk not in returned_ids
    assert private_image.title not in response.content.decode()
    assert private_image.file.url not in response.content.decode()

    detail_response = api_client.get(_detail_url(private_image), format="json")
    assert detail_response.status_code == 404
    assert private_image.title not in detail_response.content.decode()
    assert private_image.file.url not in detail_response.content.decode()
