import pytest

from cast.models import Gallery, get_or_create_gallery, sync_media_ids


@pytest.mark.parametrize(
    "from_database, from_body, expected_to_add, expected_to_remove",
    [
        # from_database, from_body, expected_to_add, expected_to_remove
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
def test_sync_media_ids(from_database, from_body, expected_to_add, expected_to_remove):
    assert sync_media_ids(from_database, from_body) == (expected_to_add, expected_to_remove)


@pytest.mark.django_db()
def test_post_media_sync(post_with_gallery, python_body, body):
    post = post_with_gallery

    # make sure gallery from body was added to post.galleries
    gallery_id = list(post.media_ids_from_body["gallery"])[0]
    gallery_ids_in_db = {g.id for g in post.galleries.all()}
    assert gallery_id in gallery_ids_in_db

    # make sure removing gallery from body removes it from db
    post.body = body
    post.save()
    gallery_ids_in_db = {g.id for g in post.galleries.all()}
    assert gallery_id not in gallery_ids_in_db


def test_get_or_create_gallery_empty_image_ids():
    assert get_or_create_gallery([]) is None


@pytest.mark.django_db()
def test_get_or_create_gallery_invalid_image_id():
    gallery = get_or_create_gallery(
        [
            0,
        ]
    )
    assert gallery is None


@pytest.mark.django_db()
def test_get_or_create_gallery_new_gallery(image):
    image_ids = [
        image.pk,
    ]
    actual_gallery = get_or_create_gallery(image_ids)
    expected_gallery = Gallery.objects.filter(images__in=[image]).first()
    assert actual_gallery == expected_gallery
    assert image_ids == [i.id for i in expected_gallery.images.all()]


@pytest.mark.django_db()
def test_get_or_create_gallery_get_already_existing(image):
    image_ids = [
        image.pk,
    ]
    expected_gallery = Gallery.objects.create()
    expected_gallery.images.add(*image_ids)
    actual_gallery = get_or_create_gallery(image_ids)
    assert actual_gallery == expected_gallery
