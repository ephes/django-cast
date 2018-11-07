import pytest
from django.urls import reverse


class TestFeed:
    @pytest.mark.django_db
    def test_get_feed(self, client, post):
        feed_url = reverse("cast:post_feed", kwargs={"slug": post.blog.slug})

        r = client.get(feed_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "xml" in content
        assert post.title in content
