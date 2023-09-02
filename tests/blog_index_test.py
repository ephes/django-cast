import pytest

from cast import appsettings
from cast.models.index_pages import Blog


class TestBlogIndex:
    pytestmark = pytest.mark.django_db

    def test_post_in_blog_index(self, client, post):
        blog_url = post.blog.get_url()

        r = client.get(blog_url)
        assert r.status_code == 200

        assert post in r.context["posts"]

    def test_unpublished_post_not_in_blog_index(self, client, unpublished_post):
        blog_url = unpublished_post.blog.get_url()

        r = client.get(blog_url)
        assert r.status_code == 200

        assert unpublished_post not in r.context["posts"]

    def test_post_overview_content_in_blog_index_but_not_detail(self, client, post):
        blog_url = post.blog.get_url()

        r = client.get(blog_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "in_all" in content
        assert "only_in_detail" not in content

    def test_post_in_blog_noindex_flag(self, client, post):
        # Set the noindex flag for the blog
        blog = post.blog
        blog.noindex = True
        blog.save()

        # Make sure the blog index page contains the noindex meta tag
        blog_url = post.blog.get_url()
        r = client.get(blog_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert '<meta name="robots" content="noindex">' in content

        # Make sure the post detail page contains the noindex meta tag
        post_url = post.get_url()
        r = client.get(post_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert '<meta name="robots" content="noindex">' in content

    def test_blog_template_base_dir_overwrites_site_setting(self, simple_request):
        blog = Blog(template_base_dir="plain")
        chosen_base_dir = "foobar"
        blog.template_base_dir = chosen_base_dir
        template = blog.get_template(simple_request)
        assert chosen_base_dir in template

    def test_session_template_base_dir_overwrites_blog_setting(self, simple_request):
        blog = Blog(template_base_dir="plain")
        chosen_base_dir = "from_session"
        simple_request.session["template_base_dir"] = "from_session"
        template = blog.get_template(simple_request)
        assert chosen_base_dir in template

    def test_blog_use_partial_template_for_htmx_request_without_target(self, caplog, htmx_request_without_target):
        Blog().get_template(htmx_request_without_target)
        assert "HTMX target is None" in caplog.text

    def test_blog_use_partial_template_for_htmx_request(self, htmx_request):
        blog = Blog()
        template = blog.get_template(htmx_request)
        assert "_list_of_posts_and_paging_controls.html" in template

    def test_post_in_blog_inherits_template_base_dir(self, post):
        blog = post.blog
        chosen_base_dir = "foobar"
        blog.template_base_dir = chosen_base_dir
        template = post.get_template(None)
        assert chosen_base_dir in template


class TestBlogIndexFilter:
    pytestmark = pytest.mark.django_db

    def test_date_facet_filter_shown(self, client, post_with_date):
        blog_url = post_with_date.blog.get_url()
        r = client.get(blog_url)
        assert r.status_code == 200

        date_to_find = post_with_date.visible_date.strftime("%Y-%m")
        content = r.content.decode("utf-8")
        assert "html" in content
        assert date_to_find in content

    def test_date_facet_filter_shown_exclusively(self, client, post_with_date, post_with_different_date):
        blog_url = post_with_date.blog.get_url()
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

    def test_selecting_non_existing_date_facet_filters_all_posts(self, client, post_with_date):
        blog_url = post_with_date.blog.get_url()
        blog_url = f"{blog_url}?date_facets=1999-01"
        r = client.get(blog_url)
        assert r.status_code == 200
        assert len(r.context["posts"]) == 0

    def test_date_facet_garbage(self, client, post_with_date):
        blog_url = post_with_date.blog.get_url()
        blog_url = f"{blog_url}?date_facets=garbage"
        r = client.get(blog_url)
        assert r.status_code == 200

        date_to_find = post_with_date.visible_date.strftime("%Y-%m")
        content = r.content.decode("utf-8")
        assert "html" in content
        assert date_to_find in content


class TestBlogIndexSearch:
    pytestmark = pytest.mark.django_db

    def test_fulltext_search_all(self, client, post, post_with_search):
        blog_url = post.blog.get_url()
        r = client.get(blog_url)
        assert r.status_code == 200

        # assert initially both posts are in the post list
        assert len(r.context["posts"]) == 2

    def test_fulltext_search_title(self, client, post, post_with_search):
        blog_url = post.blog.get_url()
        blog_url_title = f"{blog_url}?search={post_with_search.title}"
        r = client.get(blog_url_title)
        assert r.status_code == 200

        # assert search by title only yields post_with search
        posts = r.context["posts"]
        assert len(posts) == 1
        assert posts[0].pk == post_with_search.pk

    def test_fulltext_search_body(self, client, post, post_with_search):
        blog_url = post.blog.get_url()
        blog_url_content = f"{blog_url}?search={post_with_search.query}"
        r = client.get(blog_url_content)
        assert r.status_code == 200

        # assert search by title only yields post_with search
        posts = r.context["posts"]
        assert len(posts) == 1
        assert posts[0].pk == post_with_search.pk


@pytest.fixture()
def post_list_paginate_by_1():
    previous = appsettings.POST_LIST_PAGINATION
    appsettings.POST_LIST_PAGINATION = 1
    yield appsettings.POST_LIST_PAGINATION
    appsettings.POST_LIST_PAGINATION = previous


class TestBlogIndexPagination:
    pytestmark = pytest.mark.django_db

    def test_one_post_is_not_paginated(self, client, post):
        blog_url = post.blog.get_url()
        r = client.get(blog_url)
        assert r.status_code == 200

        # make sure list of posts is not paginated
        assert r.context["is_paginated"] is False

    def test_two_posts_are_paginated_with_pagination_1(self, client, post, post_with_search, post_list_paginate_by_1):
        blog_url = post.blog.get_url()
        r = client.get(blog_url)
        assert r.status_code == 200

        # make sure posts queryset is paginated and len(posts) == 1
        assert r.context["is_paginated"] is True
        assert len(r.context["posts"]) == 1

    def test_invalid_page_param(self, client, post):
        blog_url = post.blog.get_url()
        blog_url_with_invalid_page = f"{blog_url}?page=foo"
        r = client.get(blog_url_with_invalid_page)
        assert r.status_code == 404

    def test_page_param_last(self, client, post):
        blog_url = post.blog.get_url()
        blog_url_with_last_page = f"{blog_url}?page=last"
        r = client.get(blog_url_with_last_page)
        assert r.status_code == 200

    def test_invalid_page_number(self, client, post):
        blog_url = post.blog.get_url()
        blog_url_with_invalid_pagenum = f"{blog_url}?page=666"
        r = client.get(blog_url_with_invalid_pagenum)
        assert r.status_code == 404
