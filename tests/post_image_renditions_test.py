import pytest

from cast.models import Post
from cast.models.image_renditions import (
    get_all_filterstrings,
    get_gallery_thumbnail_srgb_counterpart_filterstrings,
    get_obsolete_and_missing_rendition_strings,
)


@pytest.mark.django_db
def test_post_image_in_get_all_images_from_queryset(post_with_image):
    # Given a post with an image
    [post_image] = post_with_image.images.all()
    # When we get all images from the queryset including the post
    post_queryset = Post.objects.filter(pk=post_with_image.pk).prefetch_related("images")
    all_images = {image for image_type, image in Post.get_all_images_from_queryset(post_queryset)}
    # Then the image should be in the list
    assert post_image in all_images


@pytest.mark.django_db
def test_post_image_from_gallery_in_get_all_images_from_queryset(post_with_gallery):
    # Given a post with a gallery with an image
    [post_gallery] = post_with_gallery.galleries.all()
    [gallery_image] = post_gallery.images.all()
    # When we get all images from the queryset including the post
    post_queryset = Post.objects.filter(pk=post_with_gallery.pk).prefetch_related("galleries__images")
    all_images = {image for image_type, image in Post.get_all_images_from_queryset(post_queryset)}
    # Then the image should be in the list
    assert gallery_image in all_images


@pytest.mark.django_db
def test_post_get_all_renditions_from_queryset(post_with_image):
    image = post_with_image.images.first()
    post_queryset = Post.objects.filter(pk=post_with_image.pk).prefetch_related("galleries__images")
    all_renditions = list(Post.get_all_renditions_from_queryset(post_queryset))
    assert all_renditions == [image.pk]


class StubWagtailImage:
    class File:
        name = "test.jpg"

    pk = 1
    width = 6000
    height = 4000
    file = File()


class SecondStubWagtailImage(StubWagtailImage):
    pk = 2


def test_post_get_all_required_filter_strings():
    # Given an iterator ofr images with types
    images = [("regular", StubWagtailImage())]
    # When we get all required filter strings for the image
    required_filter_strings = {fs for ipk, fs in get_all_filterstrings(images)}  # type: ignore
    # Then the required filter strings should be in the list
    assert "width-1110" in required_filter_strings


class RenditionQuerysetStub:
    unrelated_width_pk = 3
    wagtail_admin_pk = 4
    unrelated_fill_pk = 5
    old_gallery_thumbnail_pk = 6
    old_gallery_jpeg_thumbnail_pk = 7
    unrelated_format_pk = 8
    unrelated_width_format_pk = 9
    modal_srgb_pk = 10
    same_filter_other_image_pk = 11
    srgb_gallery_thumbnail_pk = 12
    srgb_gallery_avif_thumbnail_pk = 13

    def values_list(self, *_args):
        return [
            (self.unrelated_width_pk, 1, "width-400"),
            (self.wagtail_admin_pk, 1, "max-165x165"),
            (self.unrelated_fill_pk, 1, "fill-1x1"),
            (self.old_gallery_thumbnail_pk, 1, "width-120|format-avif"),  # old pre-srgb gallery thumbnail
            (self.old_gallery_jpeg_thumbnail_pk, 1, "width-120"),  # old pre-srgb gallery thumbnail
            (self.unrelated_format_pk, 1, "format-webp"),
            (self.unrelated_width_format_pk, 1, "width-800|format-webp"),
            (self.modal_srgb_pk, 1, "width-1110|srgb"),
            (self.same_filter_other_image_pk, 2, "width-120|format-avif"),
            (self.srgb_gallery_thumbnail_pk, 1, "width-120|srgb"),
            (self.srgb_gallery_avif_thumbnail_pk, 1, "width-120|srgb|format-avif"),
        ]


@pytest.mark.django_db
def test_post_get_obsolete_and_missing_rendition_strings(mocker):
    # Given an iterator of images with types
    images = [("gallery", StubWagtailImage()), ("regular", SecondStubWagtailImage())]
    # And a stub for the Rendition queryset
    rendition_queryset = RenditionQuerysetStub()
    mocker.patch("cast.models.pages.Rendition.objects.filter", return_value=rendition_queryset)
    # When we get all obsolete and missing renditions for the images
    obsolete_renditions, missing_renditions = get_obsolete_and_missing_rendition_strings(images)
    # Then only old gallery thumbnail sRGB-policy counterparts should be considered obsolete
    assert obsolete_renditions == {
        rendition_queryset.old_gallery_thumbnail_pk,
        rendition_queryset.old_gallery_jpeg_thumbnail_pk,
    }
    # Then the missing renditions should be in the list
    assert "width-240|srgb" in missing_renditions[1]


def test_gallery_thumbnail_srgb_counterpart_filterstrings_handles_missing_thumbnail_slot(settings):
    settings.CAST_GALLERY_IMAGE_SLOT_DIMENSIONS = [(1110, 740)]

    counterparts = list(get_gallery_thumbnail_srgb_counterpart_filterstrings(StubWagtailImage()))  # type: ignore[arg-type]

    assert counterparts == []


def test_post_get_obsolete_and_missing_rendition_strings_for_disabled_srgb_policy(mocker, settings):
    settings.CAST_GALLERY_THUMBNAIL_RENDITIONS_SRGB = False
    images = [("gallery", StubWagtailImage())]
    rendition_queryset = RenditionQuerysetStub()
    mocker.patch("cast.models.pages.Rendition.objects.filter", return_value=rendition_queryset)

    obsolete_renditions, missing_renditions = get_obsolete_and_missing_rendition_strings(images)

    assert obsolete_renditions == {
        rendition_queryset.srgb_gallery_thumbnail_pk,
        rendition_queryset.srgb_gallery_avif_thumbnail_pk,
    }
    assert "width-240" in missing_renditions[1]
