import pytest


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
        detail_url = post_with_gallery.get_url()

        r = client.get(detail_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "cast-gallery-thumbnail" in content
