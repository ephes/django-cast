from datetime import datetime

import pytest
from django.http import QueryDict
from django.utils.timezone import make_aware

from cast.filters import (
    CategoryFacetFilter,
    CountFacetWidget,
    PostFilterset,
    SlugChoicesField,
)
from cast.models import Post, PostCategory
from tests.factories import PostFactory


def test_count_facet_widget_render():
    cfw = CountFacetWidget()
    cfw.choices = [("foo", ("bar", "baz"))]
    cfw.data = {}
    html = cfw.render("foo", "bar")  # noqa pycharm warning about template not found
    assert "foo" in html
    assert "bar" in html
    assert "baz" in html


def test_count_facet_widget_if_options(mocker):
    mocker.patch("cast.filters.CountFacetWidget.render_options", return_value=False)
    cfw = CountFacetWidget()
    html = cfw.render("foo", "bar")  # noqa pycharm warning about template not found
    assert "foo" not in html


def test_active_pagination_is_removed_from_count_facet_filter():
    cfw = CountFacetWidget()
    cfw.data = QueryDict("page=3")
    option = cfw.render_option("name", set(), "value", "label")
    assert "page=3" not in option


def test_selected_count_facet_is_in_hidden_input():
    cfw = CountFacetWidget()
    cfw.data = QueryDict("date_facets=2018-12")
    option = cfw.render_option("date_facets", {"2018-12"}, "2018-12", "2018-12 (3)")
    assert '<input type="hidden" name="date_facets" value="2018-12">' in option


@pytest.mark.parametrize(
    "value, is_valid",
    [
        (None, False),
        ("", False),
        ("foo", True),  # happy path
        ("foo bar", False),  # no spaces
    ],
)
def test_validate_category_facet_choice(value, is_valid):
    field = SlugChoicesField()
    assert field.valid_value(value) == is_valid


def test_category_choices_mixin_filters_facets_with_count_0():
    ccm = CategoryFacetFilter()  # use Filter instead of Mixin to make super and self.extra work
    ccm.facet_counts = {"count1": ("count one", 1), "count0": ("count 0", 0)}
    _ = ccm.field
    category_slugs = {slug for slug, label in ccm.extra["choices"]}
    assert category_slugs == {"count1"}


@pytest.mark.django_db
class TestPostFilterset:
    def test_data_is_none(self):
        filterset = PostFilterset(None)
        assert filterset.data == QueryDict("")

    def test_queryset_is_none(self):
        filterset = PostFilterset(None, queryset=None)
        assert filterset.qs.count() == 0

    def test_no_posts_no_date_facets(self):
        # given a filterset with no posts
        queryset = Post.objects.none()
        # when the facet counts are fetched
        filterset = PostFilterset(QueryDict(), queryset=queryset, fetch_facet_counts=True)
        # then there are no date facets
        assert filterset.filters["date_facets"].facet_counts == {}

    def test_post_is_counted_in_date_facets(self, post):
        # given a queryset with a post
        queryset = post.blog.unfiltered_published_posts
        # when the facet counts are fetched
        filterset = PostFilterset(QueryDict(), queryset=queryset, fetch_facet_counts=True)
        # then the post is counted in the date facets
        date_facets = filterset.filters["date_facets"].facet_counts
        date_month_post = make_aware(datetime(post.visible_date.year, post.visible_date.month, 1))
        assert date_facets[date_month_post] == 1

    def test_post_is_counted_in_date_facets_when_in_search_result(self, post):
        # given a queryset with a post
        queryset = post.blog.unfiltered_published_posts
        # when the queryset is filtered by the posts title
        querydict = QueryDict(f"search={post.title}")
        filterset = PostFilterset(querydict, queryset=queryset, fetch_facet_counts=True)
        # then the post is in the queryset
        assert post in filterset.qs
        # and the post is counted in the date facets
        date_facets = filterset.filters["date_facets"].facet_counts
        date_month_post = make_aware(datetime(post.visible_date.year, post.visible_date.month, 1))
        assert date_facets[date_month_post] == 1

    def test_post_is_counted_in_date_facets_when_not_in_search_result(self, post):
        # given a queryset with a post
        queryset = post.blog.unfiltered_published_posts
        # when the queryset is filtered by a query that does not match the post
        querydict = QueryDict("search=not_in_title")
        filterset = PostFilterset(querydict, queryset=queryset, fetch_facet_counts=True)
        # then the post is not in the queryset
        assert post not in filterset.qs
        # and the post is not counted in the date facets
        date_facets = filterset.filters["date_facets"].facet_counts
        assert date_facets == {}

    def test_post_is_counted_in_category_facets(self, post):
        # given a queryset with a post in a category
        category = PostCategory.objects.create(name="Today I Learned", slug="til")
        post.categories.add(category)
        post.save()  # yes, this is required
        queryset = post.blog.unfiltered_published_posts
        # when the facet counts are fetched
        filterset = PostFilterset(QueryDict(), queryset=queryset, fetch_facet_counts=True)
        # then the post is counted in the category facets
        category_facets = filterset.filters["category_facets"].facet_counts
        assert category_facets[category.slug] == ("Today I Learned", 1)

    def test_posts_are_filtered_by_category_facet(self, post, body):
        # given a queryset with a post in a category and another post without a category
        category = PostCategory.objects.create(name="Today I Learned", slug="til")
        post.categories.add(category)
        post.save()
        blog = post.blog
        another_post = PostFactory(owner=blog.owner, parent=blog, title="another post", slug="another-post", body=body)
        another_post.save()
        # when the posts are filtered by the category
        queryset = blog.unfiltered_published_posts
        querydict = QueryDict("category_facets=til")
        filterset = PostFilterset(querydict, queryset=queryset)
        # then the post without a category is not in the queryset
        assert another_post not in filterset.qs
        assert filterset.qs.count() == 1

    def test_posts_are_filtered_and_wise_by_multiple_categories(self, post, body):
        # given a queryset containing two posts being in one category and one of the posts is
        # in an additional category

        # first post
        category = PostCategory.objects.create(name="Today I Learned", slug="til")
        post.categories.add(category)
        another_category = PostCategory.objects.create(name="Additional Category", slug="additional_category")
        post.categories.add(another_category)
        post.save()

        # second post
        blog = post.blog
        another_post = PostFactory(owner=blog.owner, parent=blog, title="another post", slug="another-post", body=body)
        another_post.categories.add(category)
        another_post.save()
        queryset = blog.unfiltered_published_posts

        # when the posts are filtered by both categories
        querydict = QueryDict("category_facets=til&category_facets=additional_category")
        filterset = PostFilterset(querydict, queryset=queryset)

        # then the post without the additional category is not in the queryset
        # but the post with both categories is in the queryset
        assert post in filterset.qs
        assert another_post not in filterset.qs
        assert filterset.qs.count() == 1

    def test_posts_are_filtered_by_tag_facet(self, post, body):
        # given a queryset with a tagged post and another post without this tag
        post.tags.add("tag")
        post.save()
        blog = post.blog
        another_post = PostFactory(owner=blog.owner, parent=blog, title="another post", slug="another-post", body=body)
        another_post.save()
        # when the posts are filtered by the tag
        queryset = blog.unfiltered_published_posts
        querydict = QueryDict("tag_facets=tag")
        filterset = PostFilterset(querydict, queryset=queryset, fetch_facet_counts=True)
        # then the untagged post is not in the queryset
        assert another_post not in filterset.qs
        assert filterset.qs.count() == 1
