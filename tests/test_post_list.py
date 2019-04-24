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

    def test_get_post_list_without_draft(self, client, draft_post):
        blog_url = reverse("cast:post_list", kwargs={"slug": draft_post.blog.slug})

        r = client.get(blog_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "html" in content
        assert draft_post.title not in content

    def test_get_post_list_without_draft_logged_in(self, client, user, draft_post):
        blog_url = reverse("cast:post_list", kwargs={"slug": draft_post.blog.slug})

        r = client.login(username=user.username, password=user._password)
        r = client.get(blog_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "html" in content
        assert draft_post.title in content
