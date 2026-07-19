from datetime import timedelta

import pytest
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from cast.devdata import create_image
from cast.models import Gallery, get_or_create_gallery, sync_media_ids
from cast.post_media import prepare_post_media, prepare_published_post_media


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
    assert gallery_id in gallery_ids_in_db

    prepare_post_media(post)
    gallery_ids_in_db = {g.id for g in post.galleries.all()}
    assert gallery_id not in gallery_ids_in_db


@pytest.mark.django_db()
def test_publishing_prepares_post_media(post_with_image):
    image = post_with_image.images.first()
    post_with_image.images.remove(image)

    post_with_image.save_revision().publish()

    assert image in post_with_image.images.all()


@pytest.mark.django_db()
def test_scheduling_initial_publication_defers_media_preparation(monkeypatch, blog, body_with_image):
    from tests.factories import PostFactory

    calls = []
    monkeypatch.setattr("cast.post_media.prepare_post_media", calls.append)
    post = PostFactory(
        owner=blog.owner,
        parent=blog,
        title="future post",
        slug="future-post",
        live=False,
        first_published_at=None,
        go_live_at=timezone.now() + timedelta(days=1),
        body=body_with_image,
    )
    calls.clear()

    post.save_revision().publish()

    assert calls == []


@pytest.mark.django_db()
def test_scheduled_publication_prepares_media_when_post_goes_live(monkeypatch, blog, body_with_image):
    from tests.factories import PostFactory

    calls = []
    monkeypatch.setattr("cast.post_media.prepare_post_media", calls.append)
    due = timezone.now() - timedelta(minutes=1)
    post = PostFactory(
        owner=blog.owner,
        parent=blog,
        title="due post",
        slug="due-post",
        live=False,
        first_published_at=None,
        go_live_at=due,
        body=body_with_image,
    )
    calls.clear()
    post.save_revision(approved_go_live_at=due)

    call_command("publish_scheduled", verbosity=0)

    assert [candidate.pk for candidate in calls] == [post.pk]


@pytest.mark.django_db()
def test_scheduling_live_post_update_does_not_prepare_media_early(monkeypatch, post_with_image):
    calls = []
    monkeypatch.setattr("cast.post_media.prepare_post_media", calls.append)
    post_with_image.go_live_at = timezone.now() + timedelta(days=1)

    post_with_image.save_revision().publish()

    assert calls == []


def test_published_media_handler_ignores_non_posts():
    prepare_published_post_media(sender=object, instance=object())


def test_post_sync_media_ids_compatibility_adapter(mocker):
    from cast.models import Post

    synchronize = mocker.patch("cast.models.pages.synchronize_post_media")
    post = Post()

    post.sync_media_ids()

    synchronize.assert_called_once_with(post)


def test_prepare_post_media_can_disable_both_operations():
    prepare_post_media(object(), sync_media=False, create_renditions=False)


@pytest.mark.django_db()
def test_media_sync_accepts_image_instances_in_gallery_blocks(image):
    class GalleryBlock:
        block_type = "gallery"
        value = {"gallery": [image]}

    class ContentBlock:
        value = [GalleryBlock()]

    from cast.models.pages import Post

    assert Post()._media_ids_from_body([ContentBlock()])["gallery"]


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
