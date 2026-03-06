import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from cast.devdata import create_image
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


def test_gallery_signature_is_empty_for_no_images():
    assert Gallery.build_signature([]) == ""


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
    assert expected_gallery.signature == Gallery.build_signature(image_ids)


@pytest.mark.django_db()
def test_get_or_create_gallery_get_already_existing(image):
    image_ids = [
        image.pk,
    ]
    expected_gallery = Gallery.objects.create()
    expected_gallery.images.add(*image_ids)
    actual_gallery = get_or_create_gallery(image_ids)
    assert actual_gallery == expected_gallery


@pytest.mark.django_db()
def test_gallery_signature_is_deterministic_for_effective_image_set(image):
    other_image = create_image()

    assert Gallery.build_signature([image.pk, other_image.pk]) == Gallery.build_signature(
        [other_image.pk, image.pk, image.pk]
    )


@pytest.mark.django_db()
def test_get_or_create_gallery_reuses_existing_gallery_for_same_images_in_any_order(image):
    other_image = create_image()
    expected_gallery = Gallery.objects.create()
    expected_gallery.images.add(image.pk, other_image.pk)

    actual_gallery = get_or_create_gallery([other_image.pk, image.pk])

    assert actual_gallery == expected_gallery


@pytest.mark.django_db()
def test_get_or_create_gallery_ignores_nonexistent_image_ids_when_reusing_gallery(image):
    other_image = create_image()
    expected_gallery = Gallery.objects.create()
    expected_gallery.images.add(image.pk, other_image.pk)

    actual_gallery = get_or_create_gallery([999999, other_image.pk, image.pk])

    assert actual_gallery == expected_gallery


@pytest.mark.django_db()
def test_get_or_create_gallery_reuses_gallery_via_signature_lookup(image):
    other_image = create_image()
    gallery = get_or_create_gallery([image.pk, other_image.pk])
    assert gallery is not None
    gallery.refresh_from_db()

    with CaptureQueriesContext(connection) as queries:
        reused_gallery = get_or_create_gallery([other_image.pk, image.pk])

    assert reused_gallery == gallery
    assert gallery.signature == Gallery.build_signature([image.pk, other_image.pk])
    sql_statements = [query["sql"] for query in queries.captured_queries]
    assert any("signature" in sql for sql in sql_statements)
    assert all("cast_gallery_images" not in sql for sql in sql_statements)


@pytest.mark.django_db()
def test_gallery_signature_refreshes_after_image_deletion(image):
    other_image = create_image()
    gallery = get_or_create_gallery([image.pk, other_image.pk])
    assert gallery is not None

    other_image.delete()
    gallery.refresh_from_db()

    assert gallery.signature == Gallery.build_signature([image.pk])
    assert get_or_create_gallery([image.pk]) == gallery


@pytest.mark.django_db
def test_serve_preview_calls_media_sync(rf, post_with_image):
    image = post_with_image.images.first()
    post_with_image.images.remove(image)  # remove image link
    assert image not in post_with_image.images.all()

    request = rf.get("/post/1/")
    post_with_image.serve_preview(request, "draft")
    assert image in post_with_image.images.all()
