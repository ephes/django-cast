import pytest
from django.urls import reverse
from cast.appsettings import CAST_COMMENTS_ENABLED

class TestComments:
    pytestmark = pytest.mark.django_db

    def test_comments_form_not_included(self, client, post, comments_disabled):
        
        slugs = {"blog_slug": post.blog.slug, "slug": post.slug}
        detail_url = reverse("cast:post_detail", kwargs=slugs)

        r = client.get(detail_url)
        assert r.status_code == 200
        
        content = r.content.decode("utf-8")
        
        assert post.title in content
        assert "comment" not in content

    def test_comments_form_included(self, client, post, comments_enabled):
        
        slugs = {"blog_slug": post.blog.slug, "slug": post.slug}
        detail_url = reverse("cast:post_detail", kwargs=slugs)

        r = client.get(detail_url)
        assert r.status_code == 200
        
        content = r.content.decode("utf-8")
        
        assert post.title in content
        assert "comment" in content
