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

    def test_get_post_list_without_draft(self, client, unpublished_post):
        blog_url = unpublished_post.blog.get_url()

        r = client.get(blog_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "html" in content
        assert unpublished_post.title not in content

    def test_get_post_list_without_draft_logged_in(self, client, user, unpublished_post):
        blog_url = reverse("cast:post_list", kwargs={"slug": unpublished_post.blog.slug})

        r = client.login(username=user.username, password=user._password)
        r = client.get(blog_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "html" in content
        assert unpublished_post.title in content

    def test_get_post_list_without_post_detail(self, client, post):
        blog_url = post.blog.get_url()

        r = client.get(blog_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "in_all" in content
        assert "only_in_detail" not in content


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


# FIXME search postponed
# class TestPostListSearch:
#     pytestmark = pytest.mark.django_db

#     def test_fulltext_search_all(self, client, post, post_with_search):
#         blog_url = reverse("cast:post_list", kwargs={"slug": post.blog.slug})
#         r = client.get(blog_url)
#         assert r.status_code == 200

#         # assert initially both posts are in the post list
#         assert len(r.context["posts"]) == 2

#     def test_fulltext_search_title(self, client, post, post_with_search):
#         blog_url = reverse("cast:post_list", kwargs={"slug": post.blog.slug})
#         blog_url_title = f"{blog_url}?search={post_with_search.title}"
#         r = client.get(blog_url_title)
#         assert r.status_code == 200

#         # assert search by title only yields post_with search
#         posts = r.context["posts"]
#         assert len(posts) == 1
#         assert posts[0].pk == post_with_search.pk

#     def test_fulltext_search_content(self, client, post, post_with_search):
#         blog_url = post_with_search.blog.get_url()
#         blog_url_content = f"{blog_url}?search={post_with_search.title}"
#         r = client.get(blog_url_content)
#         assert r.status_code == 200

#         # assert search by title only yields post_with search
#         posts = r.context["posts"]
#         assert len(posts) == 1
#         assert posts[0].pk == post_with_search.pk
