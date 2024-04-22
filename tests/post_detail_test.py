import pytest

from cast.models import Post
from cast.models.image_renditions import (
    create_missing_renditions_for_posts,
    get_all_images_from_posts,
    get_obsolete_and_missing_rendition_strings,
)


class TestPostDetail:
    pytestmark = pytest.mark.django_db

    def test_get_post_detail(self, client, post):
        detail_url = post.get_url()

        r = client.get(detail_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "html" in content
        assert post.title in content

    def test_get_post_detail_with_detail(self, client, post):
        detail_url = post.get_url()

        r = client.get(detail_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "in_all" in content
        assert "only_in_detail" in content

    def test_post_detail_with_gallery(self, client, post_with_gallery):
        create_missing_renditions_for_posts([post_with_gallery])
        images_with_type = get_all_images_from_posts([post_with_gallery])
        _, missing_renditions = get_obsolete_and_missing_rendition_strings(images_with_type)
        print("missing renditions: ", missing_renditions)
        from wagtail.images.models import Image

        for image_id, filter_specs in missing_renditions.items():
            image = Image.objects.get(id=image_id)
            print("create renditions for image: ", image.pk, filter_specs)
            foo = image.get_renditions(*filter_specs)
            for fstr, rend in foo.items():
                rend.save()
                print("fstr: ", fstr)
                print("rend: ", rend.pk)

        renditions = Post.get_all_renditions_from_queryset([post_with_gallery])
        print("all renditions: ", renditions)
        detail_url = post_with_gallery.get_url()

        r = client.get(detail_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "cast-gallery-thumbnail" in content
