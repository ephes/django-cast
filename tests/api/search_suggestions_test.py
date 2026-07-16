import json
from datetime import datetime

import pytest
from django.urls import reverse
from django.utils import timezone
from wagtail.models import PageViewRestriction

from cast.models import PostCategory
from cast.search_suggestions import TYPEAHEAD_RESULT_LIMIT, get_search_suggestions

from tests.factories import PostFactory


def suggestion_url(blog) -> str:
    return reverse("cast:api:search-suggestions-detail", kwargs={"pk": blog.pk})


@pytest.mark.django_db
def test_short_and_normalized_queries(api_client, blog):
    short = api_client.get(suggestion_url(blog), {"search": " h "})
    normalized = api_client.get(suggestion_url(blog), {"search": "  hello---world\x00  "})

    assert short.status_code == 200
    assert short.json() == {"query": "h", "suggestions": []}
    assert normalized.status_code == 200
    assert normalized.json() == {"query": "hello world", "suggestions": []}


@pytest.mark.django_db
def test_title_prefix_response_is_recent_first_and_body_only_match_is_excluded(api_client, blog, python_body):
    older = PostFactory(owner=blog.owner, parent=blog, title="Hello older", slug="hello-older", body="[]")
    newer = PostFactory(owner=blog.owner, parent=blog, title="Hello newer", slug="hello-newer", body="[]")
    body_only = list(python_body)
    body_only[0]["value"][0]["value"] = "<p>Hello only in the body</p>"
    PostFactory(
        owner=blog.owner,
        parent=blog,
        title="Unrelated title",
        slug="unrelated-title",
        body=json.dumps(body_only),
    )

    older.last_published_at = timezone.make_aware(datetime(2025, 1, 1))
    older.save()
    newer.last_published_at = timezone.make_aware(datetime(2026, 1, 1))
    newer.save()

    response = api_client.get(suggestion_url(blog), {"search": "hel"})

    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"
    result = response.json()
    assert result["query"] == "hel"
    assert [suggestion["title"] for suggestion in result["suggestions"]] == ["Hello newer", "Hello older"]
    assert set(result["suggestions"][0]) == {"id", "title", "url", "visible_date"}
    assert result["suggestions"][0]["url"] == newer.get_url()


@pytest.mark.django_db
def test_facets_scope_suggestions_and_invalid_facets_are_ignored(api_client, blog):
    category = PostCategory.objects.create(name="Tutorial", slug="tutorial")
    included = PostFactory(
        owner=blog.owner,
        parent=blog,
        title="Python included",
        slug="python-included",
        body="[]",
        visible_date=timezone.make_aware(datetime(2026, 7, 10)),
    )
    included.tags.add("python")
    included.categories.add(category)
    included.save()
    PostFactory(
        owner=blog.owner,
        parent=blog,
        title="Python excluded",
        slug="python-excluded",
        body="[]",
        visible_date=timezone.make_aware(datetime(2025, 7, 10)),
    )

    response = api_client.get(
        suggestion_url(blog),
        {
            "search": "py",
            "date_facets": "2026-07",
            "tag_facets": "python",
            "category_facets": "tutorial",
        },
    )
    invalid = api_client.get(
        suggestion_url(blog),
        {"search": "py", "date_facets": "invalid", "tag_facets": "not valid!"},
    )

    assert [suggestion["id"] for suggestion in response.json()["suggestions"]] == [included.pk]
    assert {suggestion["title"] for suggestion in invalid.json()["suggestions"]} == {
        "Python included",
        "Python excluded",
    }


@pytest.mark.django_db
def test_restricted_unpublished_and_other_blog_posts_are_excluded(api_client, blog, site):
    visible = PostFactory(owner=blog.owner, parent=blog, title="Hello visible", slug="hello-visible", body="[]")
    restricted = PostFactory(
        owner=blog.owner,
        parent=blog,
        title="Hello restricted",
        slug="hello-restricted",
        body="[]",
    )
    PageViewRestriction.objects.create(page=restricted, restriction_type=PageViewRestriction.LOGIN)
    unpublished = PostFactory(
        owner=blog.owner,
        parent=blog,
        title="Hello unpublished",
        slug="hello-unpublished",
        body="[]",
    )
    unpublished.unpublish()
    other_blog = type(blog)(owner=blog.owner, title="Other blog", slug="other-blog")
    site.root_page.add_child(instance=other_blog)
    PostFactory(owner=blog.owner, parent=other_blog, title="Hello elsewhere", slug="hello-elsewhere", body="[]")

    response = api_client.get(suggestion_url(blog), {"search": "hel"})

    assert [suggestion["id"] for suggestion in response.json()["suggestions"]] == [visible.pk]


@pytest.mark.django_db
def test_result_limit(api_client, blog):
    for index in range(TYPEAHEAD_RESULT_LIMIT + 3):
        PostFactory(
            owner=blog.owner,
            parent=blog,
            title=f"Python result {index}",
            slug=f"python-result-{index}",
            body="[]",
        )

    response = api_client.get(suggestion_url(blog), {"search": "py"})

    assert len(response.json()["suggestions"]) == TYPEAHEAD_RESULT_LIMIT


@pytest.mark.django_db
def test_non_public_blog_is_not_available(api_client, blog):
    blog.unpublish()

    response = api_client.get(suggestion_url(blog), {"search": "py"})

    assert response.status_code == 404


@pytest.mark.django_db
def test_query_count_is_flat(django_assert_num_queries, blog, site):
    posts = [
        PostFactory(
            owner=blog.owner,
            parent=blog,
            title=f"Python result {index}",
            slug=f"python-query-result-{index}",
            body="[]",
        )
        for index in range(TYPEAHEAD_RESULT_LIMIT)
    ]
    get_search_suggestions(blog=blog, params={"search": "py"}, current_site=site)

    with django_assert_num_queries(2):
        result = get_search_suggestions(blog=blog, params={"search": "py"}, current_site=site)

    assert [suggestion["id"] for suggestion in result["suggestions"]] == [post.pk for post in reversed(posts)]
