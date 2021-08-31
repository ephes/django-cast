import pytest


class TestPostWithImageDetail:
    pytestmark = pytest.mark.django_db

    def test_get_post_with_image_detail(self, client, post_with_image):
        post = post_with_image
        detail_url = post.get_url()

        r = client.get(detail_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "html" in content

        # make sure css for image included in rendered image block
        assert "cast-image" in content
