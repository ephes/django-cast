import pytest

from cast.models import Post


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
    post_queryset = Post.objects.filter(pk=post_with_image.pk).prefetch_related("galleries__images")
    all_renditions = list(Post.get_all_renditions_from_queryset(post_queryset))
    assert all_renditions == []


class StubWagtailImage:
    class File:
        name = "test.jpg"

    pk = 1
    width = 6000
    height = 4000
    file = File()


def test_post_get_all_required_filter_strings():
    # Given an iterator ofr images with types
    images = [("regular", StubWagtailImage())]
    # When we get all required filter strings for the image
    required_filter_strings = {fs for ipk, fs in Post.get_all_filterstrings(images)}  # type: ignore
    # Then the required filter strings should be in the list
    assert "width-1110" in required_filter_strings


class RenditionQuerysetStub:
    pk = 3

    def values_list(self, *_args):
        return [
            (self.pk, 2, "width-1110"),  # one obsolete rendition, since image_id != 1
            (self.pk, 2, "max-165x165"),  # one wagtailadmin thumbnail that is not obsolete
        ]


@pytest.mark.django_db
def test_post_get_obsolete_and_missing_rendition_strings(mocker):
    # Given an iterator of images with types
    images = [("regular", StubWagtailImage())]
    # And a stub for the Rendition queryset
    rendition_queryset = RenditionQuerysetStub()
    mocker.patch("cast.models.pages.Rendition.objects.filter", return_value=rendition_queryset)
    # When we get all obsolete and missing renditions for the images
    obsolete_renditions, missing_renditions = Post.get_obsolete_and_missing_rendition_strings(images)
    # Then the obsolete renditions should be empty
    assert obsolete_renditions == {rendition_queryset.pk}
    # Then the missing renditions should be in the list
    assert "width-1110" in missing_renditions[1]
