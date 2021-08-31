from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

import pytest

from cast.models import Post


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
        slugs = {"blog_slug": post.blog.slug, "slug": post.slug}
        detail_url = reverse("cast:post_detail", kwargs=slugs)

        r = client.get(detail_url)
        assert r.status_code == 404

        content = r.content.decode("utf-8")
        assert post.title not in content

    def test_get_post_detail_not_published_authenticated(self, client, unpublished_post):
        post = unpublished_post
        slugs = {"blog_slug": post.blog.slug, "slug": post.slug}
        detail_url = reverse("cast:post_detail", kwargs=slugs)

        r = client.login(username=post.owner.username, password="password")

        r = client.get(detail_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "html" in content
        assert post.title in content

    def test_get_post_not_published_not_authenticated(self, client, unpublished_post):
        post = unpublished_post
        blog_url = reverse("cast:post_list", kwargs={"slug": post.blog.slug})

        r = client.get(blog_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "html" in content
        assert post.title not in content

    def test_get_post_not_published_authenticated(self, client, unpublished_post):
        post = unpublished_post
        blog_url = reverse("cast:post_list", kwargs={"slug": post.blog.slug})

        r = client.login(username=post.owner.username, password="password")

        r = client.get(blog_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "html" in content
        assert post.title in content

    def test_published_manager_pub_date_null(self, post):
        assert Post.published.count() == 1
        post.pub_date = None
        post.save()
        assert Post.objects.count() == 1
        assert Post.published.count() == 0

    def test_published_manager_future_pubdate(self, post):
        assert Post.published.count() == 1
        post.pub_date = timezone.now() + timedelta(seconds=10)
        post.save()
        assert Post.objects.count() == 1
        assert Post.published.count() == 0
        post.pub_date = timezone.now()
        post.save()
        assert Post.objects.count() == 1
        assert Post.published.count() == 1
