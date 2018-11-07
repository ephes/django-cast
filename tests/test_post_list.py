import pytest
from django.urls import reverse


class TestPostList:
    pytestmark = pytest.mark.django_db

    def test_get_post_list(self, client, post):
        blog_url = reverse("cast:post_list", kwargs={"slug": post.blog.slug})

        r = client.get(blog_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "html" in content
        assert post.title in content
