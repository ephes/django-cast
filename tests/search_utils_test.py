from django.db import models
import pytest

from cast.search_utils import normalize_modelsearch_query, safe_fulltext_queryset, safe_modelsearch_results


@pytest.mark.parametrize(
    "raw_value, expected",
    [
        ("\x00foo\x00bar", "foobar"),
        (" -- foo\t-\nbar  baz -- ", "foo bar baz"),
        ("a" * 499 + " b", "a" * 499),
        ("a" * 501, "a" * 500),
        ("ümlaut テスト", "ümlaut テスト"),
    ],
)
def test_normalize_modelsearch_query(raw_value, expected):
    assert normalize_modelsearch_query(raw_value) == expected


@pytest.mark.django_db
def test_safe_fulltext_queryset_returns_none_for_empty_normalized_search(post):
    queryset = post.blog.unfiltered_published_posts

    results = safe_fulltext_queryset(queryset, "---\x00")

    assert isinstance(results, models.QuerySet)
    assert list(results) == []


@pytest.mark.django_db
def test_safe_fulltext_queryset_searches_with_normalized_input(post):
    queryset = post.blog.unfiltered_published_posts

    results = safe_fulltext_queryset(queryset, f"\x00-{post.title}-")

    assert post in results


@pytest.mark.django_db
@pytest.mark.parametrize("fixture_name", ["audio", "video"])
def test_safe_modelsearch_results_preserves_search_results_for_normal_input(request, fixture_name):
    media = request.getfixturevalue(fixture_name)
    queryset = type(media).objects.all().order_by("-created")

    results = safe_modelsearch_results(queryset, media.title)

    assert results is not queryset
    assert list(results) == [media]


@pytest.mark.django_db
@pytest.mark.parametrize("fixture_name", ["audio", "video"])
def test_safe_modelsearch_results_returns_base_queryset_for_empty_normalized_input(request, fixture_name):
    media = request.getfixturevalue(fixture_name)
    queryset = type(media).objects.all().order_by("-created")

    results = safe_modelsearch_results(queryset, "---\x00")

    assert results is queryset
    assert list(results) == [media]
