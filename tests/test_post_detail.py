import pytest
from django.urls import reverse


class TestPostDetail:
    pytestmark = pytest.mark.django_db

    def test_get_post_detail(self, client, post):
        slugs = {"blog_slug": post.blog.slug, "slug": post.slug}
        detail_url = reverse("cast:post_detail", kwargs=slugs)

        r = client.get(detail_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "html" in content
        assert post.title in content
