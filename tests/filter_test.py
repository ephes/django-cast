from datetime import datetime

import pytest
from django.http import QueryDict
from django.utils.timezone import make_aware

from cast.filters import CountFacetWidget, PostFilterset, SlugChoicesField
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


@pytest.fixture
def post_with_tag(post):
    post.tags.add("tag")
    post.save()
    return post


@pytest.fixture
def post_with_category(post):
    category = PostCategory.objects.create(name="Today I Learned", slug="til")
    post.categories.add(category)
    post.save()  # yes, this is required
    post.category = category
    return post


@pytest.fixture()
def another_post(post, body):
    blog = post.blog
    another_post = PostFactory(owner=blog.owner, parent=blog, title="another post", slug="another-post", body=body)
    another_post.save()
    return another_post


@pytest.mark.django_db
class TestPostFilterset:
    def test_data_is_none(self):
        filterset = PostFilterset(data=None)
        assert filterset.data == QueryDict("")

    def test_queryset_is_none(self):
        filterset = PostFilterset(None, queryset=None)
        assert filterset.qs.count() == 0

    def test_no_posts_no_date_facets(self):
        # given a filterset with no posts
        queryset = Post.objects.none()
        # when the facet counts are fetched
        filterset = PostFilterset(QueryDict(), queryset=queryset)
        # then there are no date facets
        assert filterset.filters["date_facets"].facet_counts == {}

    def test_post_is_counted_in_date_facets(self, post):
        # given a queryset with a post
        queryset = post.blog.unfiltered_published_posts
        # when the facet counts are fetched
        filterset = PostFilterset(QueryDict(), queryset=queryset)
        # then the post is counted in the date facets
        date_facets = filterset.filters["date_facets"].facet_counts
        date_month_post = make_aware(datetime(post.visible_date.year, post.visible_date.month, 1))
        assert date_facets[date_month_post] == 1

    def test_post_is_counted_in_date_facets_when_in_search_result(self, post):
        # given a queryset with a post
        queryset = post.blog.unfiltered_published_posts
        # when the queryset is filtered by the posts title
        querydict = QueryDict(f"search={post.title}")
        filterset = PostFilterset(querydict, queryset=queryset)
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
        filterset = PostFilterset(querydict, queryset=queryset)
        # then the post is not in the queryset
        assert post not in filterset.qs
        # and the post is not counted in the date facets
        date_facets = filterset.filters["date_facets"].facet_counts
        assert date_facets == {}

    def test_post_is_counted_in_category_facets(self, post_with_category):
        # given a queryset with a post in a category
        post = post_with_category
        queryset = post.blog.unfiltered_published_posts
        # when the facet counts are fetched
        filterset = PostFilterset(QueryDict(), queryset=queryset)
        # then the post is counted in the category facets
        category_facets = filterset.filters["category_facets"].facet_counts
        assert category_facets[post.category.slug] == ("Today I Learned", 1)

    def test_posts_are_filtered_by_category_facet(self, post_with_category, another_post):
        # given a queryset with a post in a category and another post without a category
        post = post_with_category
        blog = post.blog
        # when the posts are filtered by the category
        queryset = blog.unfiltered_published_posts
        querydict = QueryDict("category_facets=til")
        filterset = PostFilterset(querydict, queryset=queryset)
        # then the post without a category is not in the queryset
        assert another_post not in filterset.qs
        assert filterset.qs.count() == 1

    def test_posts_are_filtered_and_wise_by_multiple_categories(self, post, another_post):
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

    def test_posts_are_filtered_by_tag_facet(self, post, another_post):
        # given a queryset with a tagged post and another post without this tag
        post.tags.add("tag")
        post.save()
        # use a tag where name and slug are different to test that the slug is used
        [tag] = post.tags.all()
        tag.slug = "foobar"
        tag.save()
        # when the posts are filtered by the tag
        queryset = post.blog.unfiltered_published_posts
        querydict = QueryDict(f"tag_facets={tag.slug}")
        filterset = PostFilterset(querydict, queryset=queryset)
        # then the untagged post is not in the queryset
        assert another_post not in filterset.qs
        assert filterset.qs.count() == 1

    def test_fields_without_facets_having_some_posts_get_removed(self, post):
        # given a queryset without a post having a category or tag
        queryset = post.blog.unfiltered_published_posts
        # when the facet counts are fetched
        filterset = PostFilterset(QueryDict(), queryset=queryset)
        # then the category and tag facet are not in the filterset form
        assert "category_facets" not in filterset.form.fields
        assert "tag_facets" not in filterset.form.fields

    def test_tag_used_for_two_posts_should_be_counted_twice(self, post, another_post):
        """
        This didn't happen because `PostTag.annotate` created the wrong group
        by clause (post_tag_id instead of tag_id).
        """
        # given two posts with the same tag
        post.tags.add("tag")
        post.save()
        another_post.tags.add("tag")
        another_post.save()
        # when the facet counts are fetched
        queryset = post.blog.unfiltered_published_posts
        filterset = PostFilterset(QueryDict(), queryset=queryset)
        # then the tag is counted twice
        tag_facets = filterset.filters["tag_facets"].facet_counts
        assert tag_facets["tag"] == ("tag", 2)

    def test_bound_field_choices_should_be_set_from_facet_counts(self, post):
        """
        If this test fails, we are in big trouble since there's a lot of magic
        necessary to make the facet counts appear in the choices.
        """
        # given a queryset with a tagged post
        post.tags.add("tag")
        post.save()
        queryset = post.blog.unfiltered_published_posts
        # when we create a filterset
        filterset = PostFilterset(QueryDict(), queryset=queryset)
        # then the tag appears in the choices of the bound field
        slugs = {slug for slug, display in filterset.form["tag_facets"].field.choices}
        assert "tag" in slugs

    def test_remove_filters_not_in_configured_filters(self, mocker):
        # given the configured_filters are an empty set
        mocker.patch("cast.filters.appsettings.CAST_FILTERSET_FACETS", return_value=[])
        # when the filterset is created
        filterset = PostFilterset(QueryDict("foo=bar"))
        # then all filters are removed
        assert filterset.filters == {}
