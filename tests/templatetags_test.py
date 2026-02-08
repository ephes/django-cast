import pytest
from django.http import QueryDict
from django.template import Context, Template
from django.test import RequestFactory

from cast.filters import PostFilterset, get_active_facets, has_active_filters
from cast.models import PostCategory


# --- remove_filter_url template tag tests ---


def _render_remove_filter_url(request, param_name):
    """Helper: render {% remove_filter_url param_name %} in a template."""
    template = Template("{% load cast_extras %}{% remove_filter_url param_name %}")
    context = Context({"request": request, "param_name": param_name})
    return template.render(context)


def test_remove_filter_url_removes_param():
    factory = RequestFactory()
    request = factory.get("/blog/", {"search": "django", "tag_facets": "python"})
    result = _render_remove_filter_url(request, "search")
    assert "search=" not in result
    assert "tag_facets=python" in result


def test_remove_filter_url_also_removes_page():
    factory = RequestFactory()
    request = factory.get("/blog/", {"search": "django", "page": "3"})
    result = _render_remove_filter_url(request, "search")
    assert "search=" not in result
    assert "page=" not in result


def test_remove_filter_url_returns_path_when_no_params_left():
    factory = RequestFactory()
    request = factory.get("/blog/", {"search": "django"})
    result = _render_remove_filter_url(request, "search")
    assert result == "/blog/"


def test_remove_filter_url_preserves_other_params():
    factory = RequestFactory()
    request = factory.get("/blog/", {"search": "django", "o": "visible_date", "tag_facets": "python"})
    result = _render_remove_filter_url(request, "o")
    assert "o=" not in result
    assert "search=django" in result
    assert "tag_facets=python" in result


# --- get_active_facets helper tests ---


@pytest.fixture
def post_with_tag_and_category(post):
    post.tags.add("python")
    category = PostCategory.objects.create(name="Today I Learned", slug="til")
    post.categories.add(category)
    post.save()
    return post


@pytest.mark.django_db
class TestGetActiveFacets:
    def test_empty_request_returns_no_facets(self, post):
        queryset = post.blog.unfiltered_published_posts
        filterset = PostFilterset(QueryDict(""), queryset=queryset)
        factory = RequestFactory()
        request = factory.get("/blog/")
        result = get_active_facets(filterset, request)
        assert result == []

    def test_tag_facet_returns_display_value(self, post):
        post.tags.add("python")
        post.save()
        queryset = post.blog.unfiltered_published_posts
        filterset = PostFilterset(QueryDict("tag_facets=python"), queryset=queryset)
        factory = RequestFactory()
        request = factory.get("/blog/", {"tag_facets": "python"})
        result = get_active_facets(filterset, request)
        assert len(result) == 1
        assert result[0]["param_name"] == "tag_facets"
        assert result[0]["label"] == "Tag"
        # display_value should include the count from the facet label
        assert "python" in result[0]["display_value"]

    def test_category_facet_returns_display_value(self, post):
        category = PostCategory.objects.create(name="Today I Learned", slug="til")
        post.categories.add(category)
        post.save()
        queryset = post.blog.unfiltered_published_posts
        filterset = PostFilterset(QueryDict("category_facets=til"), queryset=queryset)
        factory = RequestFactory()
        request = factory.get("/blog/", {"category_facets": "til"})
        result = get_active_facets(filterset, request)
        assert len(result) == 1
        assert result[0]["param_name"] == "category_facets"
        assert result[0]["label"] == "Category"
        assert "Today I Learned" in result[0]["display_value"]

    def test_date_facet_returns_display_value(self, post):
        queryset = post.blog.unfiltered_published_posts
        date_str = post.visible_date.strftime("%Y-%m")
        filterset = PostFilterset(QueryDict(f"date_facets={date_str}"), queryset=queryset)
        factory = RequestFactory()
        request = factory.get("/blog/", {"date_facets": date_str})
        result = get_active_facets(filterset, request)
        assert len(result) == 1
        assert result[0]["param_name"] == "date_facets"
        assert result[0]["label"] == "Date"
        assert date_str in result[0]["display_value"]

    def test_multiple_active_facets(self, post_with_tag_and_category):
        post = post_with_tag_and_category
        queryset = post.blog.unfiltered_published_posts
        filterset = PostFilterset(QueryDict("tag_facets=python&category_facets=til"), queryset=queryset)
        factory = RequestFactory()
        request = factory.get("/blog/", {"tag_facets": "python", "category_facets": "til"})
        result = get_active_facets(filterset, request)
        assert len(result) == 2
        param_names = {r["param_name"] for r in result}
        assert param_names == {"tag_facets", "category_facets"}

    def test_facet_not_in_form_fields_is_skipped(self, post):
        queryset = post.blog.unfiltered_published_posts
        # tag_facets field gets removed when no tags exist
        filterset = PostFilterset(QueryDict("tag_facets=nonexistent"), queryset=queryset)
        factory = RequestFactory()
        request = factory.get("/blog/", {"tag_facets": "nonexistent"})
        result = get_active_facets(filterset, request)
        assert result == []

    def test_field_without_choices_uses_raw_value(self, post):
        """When a field has no choices attribute, the raw value is used as display."""
        post.tags.add("python")
        post.save()
        queryset = post.blog.unfiltered_published_posts
        filterset = PostFilterset(QueryDict("tag_facets=python"), queryset=queryset)
        # Replace the field with a simple mock object that has no choices attribute
        from unittest.mock import MagicMock

        mock_field = MagicMock(spec=[])  # empty spec = no attributes
        filterset.form.fields["tag_facets"] = mock_field
        factory = RequestFactory()
        request = factory.get("/blog/", {"tag_facets": "python"})
        result = get_active_facets(filterset, request)
        assert len(result) == 1
        assert result[0]["display_value"] == "python"


@pytest.mark.django_db
class TestHasActiveFilters:
    def test_no_params_returns_false(self, post):
        queryset = post.blog.unfiltered_published_posts
        filterset = PostFilterset(QueryDict(""), queryset=queryset)
        factory = RequestFactory()
        request = factory.get("/blog/")
        assert has_active_filters(filterset, request) is False

    def test_page_only_returns_false(self, post):
        queryset = post.blog.unfiltered_published_posts
        filterset = PostFilterset(QueryDict("page=2"), queryset=queryset)
        factory = RequestFactory()
        request = factory.get("/blog/", {"page": "2"})
        assert has_active_filters(filterset, request) is False

    def test_search_param_returns_true(self, post):
        queryset = post.blog.unfiltered_published_posts
        filterset = PostFilterset(QueryDict("search=django"), queryset=queryset)
        factory = RequestFactory()
        request = factory.get("/blog/", {"search": "django"})
        assert has_active_filters(filterset, request) is True

    def test_ordering_param_returns_true(self, post):
        queryset = post.blog.unfiltered_published_posts
        filterset = PostFilterset(QueryDict("o=visible_date"), queryset=queryset)
        factory = RequestFactory()
        request = factory.get("/blog/", {"o": "visible_date"})
        assert has_active_filters(filterset, request) is True

    def test_tag_facet_returns_true(self, post):
        post.tags.add("python")
        post.save()
        queryset = post.blog.unfiltered_published_posts
        filterset = PostFilterset(QueryDict("tag_facets=python"), queryset=queryset)
        factory = RequestFactory()
        request = factory.get("/blog/", {"tag_facets": "python"})
        assert has_active_filters(filterset, request) is True
