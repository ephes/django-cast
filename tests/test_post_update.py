import pytest
from django.urls import reverse


class TestPostUpdate:
    pytestmark = pytest.mark.django_db

    def test_get_post_update_not_authenticated(self, client, blog, post):
        update_url = reverse(
            "cast:post_update", kwargs={"blog_slug": blog.slug, "slug": post.slug}
        )

        r = client.get(update_url)
        # redirect to login
        assert r.status_code == 302

    def test_get_post_update_authenticated(self, client, blog, post):
        update_url = reverse(
            "cast:post_update", kwargs={"blog_slug": blog.slug, "slug": post.slug}
        )
        r = client.login(username=blog.user.username, password=blog.user._password)
        r = client.get(update_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "html" in content
        assert "ckeditor" in content
