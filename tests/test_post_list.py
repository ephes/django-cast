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


class TestPostListFilter:
    pytestmark = pytest.mark.django_db

    def test_date_facet_filter_shown(self, client, post_with_date):
        blog_url = reverse("cast:post_list", kwargs={"slug": post_with_date.blog.slug})
        r = client.get(blog_url)
        assert r.status_code == 200

        date_to_find = post_with_date.visible_date.strftime("%Y-%m")
        content = r.content.decode("utf-8")
        assert "html" in content
        assert date_to_find in content

    def test_date_facet_filter_shown_exclusively(
        self, client, post_with_date, post_with_different_date
    ):
        blog_url = reverse("cast:post_list", kwargs={"slug": post_with_date.blog.slug})
        r = client.get(blog_url)
        assert r.status_code == 200

        # assert both date facets are shown
        date_to_find = post_with_date.visible_date.strftime("%Y-%m")
        different_date_to_find = post_with_different_date.visible_date.strftime("%Y-%m")
        content = r.content.decode("utf-8")
        assert "html" in content
        assert date_to_find in content
        assert different_date_to_find in content

        # assert only one date facet is shown if one is selected
        blog_url = f"{blog_url}?date_facets={date_to_find}"

        r = client.get(blog_url)
        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "html" in content
        assert date_to_find in content
        assert different_date_to_find not in content  # attention
