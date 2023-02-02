import pytest
from django.urls import reverse


class TestPublished:
    pytestmark = pytest.mark.django_db

    def test_get_only_published_entries(self, client, unpublished_post):
        bp = unpublished_post
        feed_url = reverse("cast:latest_entries_feed", kwargs={"slug": bp.blog.slug})

        r = client.get(feed_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "xml" in content
        assert bp.title not in content

    def test_get_post_detail_not_published_not_auth(self, client, unpublished_post):
        post = unpublished_post
        detail_url = post.get_url()

        r = client.get(detail_url)
        assert r.status_code == 404

        content = r.content.decode("utf-8")
        assert post.title not in content
