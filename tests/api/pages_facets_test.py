# ruff: noqa: F401,F811,I001
import json
from datetime import datetime, timedelta
from urllib.parse import urlencode

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.request import Request
from wagtail.models import PageViewRestriction

from cast import modal_facet_counts
from cast.api.serializers import AudioPodloveSerializer
from cast.api.views import (
    AudioPodloveDetailView,
    CastImagesAPIViewSet,
    FilteredPagesAPIViewSet,
    StandardResultsSetPagination,
    ThemeListView,
)
from cast.devdata import create_transcript, generate_blog_with_media
from cast.models import Audio, Contributor, EpisodeContributor, PostCategory, TranscriptSpeakerMapping

from tests.factories import PostFactory, UserFactory

SCANNER_SEARCH_PAYLOAD = "-9399862) UNION ALL SELECT CONCAT('a','b'),NULL,NULL -- -"


class TestCommentTrainingData:
    pytestmark = pytest.mark.django_db

    @classmethod
    def setup_class(cls):
        cls.url = reverse("cast:api:comment-training-data")

    def test_get_comment_training_data_without_authentication(self, api_client):
        """Should not be accessible without authentication."""
        r = api_client.get(self.url, format="json")
        assert r.status_code == 403

    def test_get_comment_training_data_with_non_staff_authentication(self, api_client):
        """Authenticated non-staff users must not access comment training data."""
        user = UserFactory()
        api_client.login(username=user.username, password="password")
        r = api_client.get(self.url, format="json")
        assert r.status_code == 403

    def test_get_comment_training_data_with_staff_authentication(self, api_client):
        """Staff users may access comment training data."""
        from django_comments import get_model as get_comments_model

        get_comments_model().objects.all().delete()
        user = UserFactory(is_staff=True)
        api_client.login(username=user.username, password="password")
        r = api_client.get(self.url, format="json")
        assert r.status_code == 200
        assert r.json() == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    "date, post_filter, len_result",
    [
        (datetime(2022, 8, 22), "true", 0),  # wrong date facet -> not found
        (None, "true", 1),  # correct date facet -> found
        (datetime(2022, 8, 22), "false", 1),  # wrong date facet and no post filter -> found
    ],
)
def test_wagtail_pages_api_with_post_filter(date, post_filter, len_result, rf, blog, post):
    viewset = FilteredPagesAPIViewSet()
    path = blog.wagtail_api_pages_url
    if date is None:
        date = timezone.localtime(post.visible_date)
    date_facet = f"{date.year}-{date.month}"
    request = rf.get(
        f"{path}?child_of={blog.pk}&type=cast.Post&date_facets={date_facet}&use_post_filter={post_filter}"
    )
    viewset.request = request
    queryset = viewset.get_queryset()
    queryset_ids = set(queryset.values_list("id", flat=True))
    if len_result:
        assert post.id in queryset_ids
    else:
        assert post.id not in queryset_ids


@pytest.mark.django_db
def test_wagtail_pages_api_with_post_filter_and_fulltext_search(rf, blog, post):
    viewset = FilteredPagesAPIViewSet()
    path = blog.wagtail_api_pages_url
    search_param = "search=foo"
    request = rf.get(f"{path}?child_of={blog.pk}&type=cast.Post&{search_param}&use_post_filter=true")
    viewset.request = request
    queryset = viewset.get_queryset()
    assert len(queryset) == 0


@pytest.mark.django_db
def test_wagtail_pages_api_template_base_dir_override(rf, blog, post):
    viewset = FilteredPagesAPIViewSet()
    path = blog.wagtail_api_pages_url
    request = rf.get(f"{path}?child_of={blog.pk}&type=cast.Post&template_base_dir=plain")
    viewset.request = request
    viewset.get_queryset()
    assert request.cast_template_base_dir == "plain"


@pytest.mark.django_db
def test_wagtail_pages_api_theme_alias_override(rf, blog, post):
    viewset = FilteredPagesAPIViewSet()
    path = blog.wagtail_api_pages_url
    request = rf.get(f"{path}?child_of={blog.pk}&type=cast.Post&theme=plain")
    viewset.request = request
    viewset.get_queryset()
    assert request.cast_template_base_dir == "plain"


def test_wagtail_pages_api_template_base_dir_invalid_choice(rf):
    viewset = FilteredPagesAPIViewSet()
    request = rf.get("/?template_base_dir=missing-theme")
    viewset.request = request
    viewset._apply_template_base_dir_override()
    assert not hasattr(request, "cast_template_base_dir")


def test_wagtail_pages_api_template_base_dir_sets_wrapped_request(rf):
    viewset = FilteredPagesAPIViewSet()
    request = Request(rf.get("/?template_base_dir=plain"))
    viewset.request = request
    viewset._apply_template_base_dir_override()
    assert request.cast_template_base_dir == "plain"
    assert request._request.cast_template_base_dir == "plain"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field_name, api_viewset_class",
    [
        ("slug", FilteredPagesAPIViewSet),
        ("title", CastImagesAPIViewSet),
    ],
)
def test_wagtail_api_viewsets_filter_null_bytes(rf, field_name, api_viewset_class):
    # Given a request filtering for a slug containing a null byte
    input_with_null_byte = "1%00%EF%BF%BD%EF%BF%BD%EF%BF%BD%EF%BF%BD%252527%252522"
    request = rf.get(f"?{field_name}={input_with_null_byte}&harmless=foo")
    viewset = api_viewset_class()
    viewset.request = request
    queryset = viewset.get_queryset()
    # When the queryset is filtered
    queryset = viewset.filter_queryset(queryset)
    # Then there should be no null bytes in the resulting SQL query params
    _sql, params = queryset.query.sql_with_params()
    assert all(["\x00" not in str(param) for param in params])


@pytest.mark.django_db
def test_facet_counts_list(api_client, blog):
    """
    Test whether the facet counts list endpoint returns a list of all blogs
    and the blog is included in the result.
    """
    url = reverse("cast:api:facet-counts-list")
    r = api_client.get(url, format="json")
    assert r.status_code == 200

    results = r.json()["results"]
    result = next(result for result in results if result["id"] == blog.pk)
    assert "id" in result
    assert "url" in result
    assert result["id"] == blog.pk


def test_facet_counts_list_post(api_client):
    """
    Someone sent a lot of post data to the facet counts list endpoint.
    Make sure she gets a proper 405 instead of a 500 next time.
    """
    url = reverse("cast:api:facet-counts-list")
    r = api_client.post(url, data={})
    assert r.status_code == 405


@pytest.mark.django_db
def test_facet_counts_detail(api_client, blog, post):
    """
    Test whether the facet counts detail endpoint returns the
    facet counts for a specific blog.
    """
    # Given a post with a category and a tag
    category = PostCategory.objects.create(name="category", slug="category")
    post.categories.add(category)
    post.tags.add("tag")
    post.save()

    # When we request the facet counts for the blog
    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})
    r = api_client.get(url, format="json")
    assert r.status_code == 200

    result = r.json()
    facet_counts = result["facet_counts"]

    # Then we expect the correct facet counts to be returned
    local_visible_date = timezone.localtime(post.visible_date)
    assert facet_counts["date_facets"][0]["slug"] == local_visible_date.strftime("%Y-%m")
    assert facet_counts["date_facets"][0]["name"] == local_visible_date.strftime("%Y-%m")
    assert facet_counts["date_facets"][0]["count"] == 1

    assert facet_counts["category_facets"][0]["slug"] == category.slug
    assert facet_counts["category_facets"][0]["count"] == 1

    assert facet_counts["tag_facets"][0]["slug"] == "tag"
    assert facet_counts["tag_facets"][0]["count"] == 1

    # make sure adding a search param filters the results
    r = api_client.get(f"{url}?search=foobar", format="json")
    assert r.status_code == 200

    result = r.json()
    date_facets = result["facet_counts"]["date_facets"]
    assert len(date_facets) == 0


@pytest.mark.django_db
def test_facet_counts_detail_unpublished_blog_returns_404(api_client, blog):
    blog.unpublish()
    blog.refresh_from_db()

    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})
    r = api_client.get(url, format="json")

    assert r.status_code == 404


@pytest.mark.django_db
def test_facet_counts_detail_live_blog_still_returns_200(api_client, blog):
    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})
    r = api_client.get(url, format="json")

    assert r.status_code == 200
    assert r.json()["id"] == blog.pk


def _create_modal_facet_posts(blog, body):
    til = PostCategory.objects.create(name="Today I Learned", slug="til")
    weeknotes = PostCategory.objects.create(name="WeekNotes", slug="weeknotes")

    jan_python = PostFactory(
        owner=blog.owner,
        parent=blog,
        title="Python January",
        slug="python-january",
        body=body,
        visible_date=timezone.make_aware(datetime(2026, 1, 10)),
    )
    jan_python.tags.add("python")
    jan_python.categories.add(til)
    jan_python.save()

    feb_django = PostFactory(
        owner=blog.owner,
        parent=blog,
        title="Django February",
        slug="django-february",
        body=body,
        visible_date=timezone.make_aware(datetime(2026, 2, 12)),
    )
    feb_django.tags.add("django")
    feb_django.categories.add(til)
    feb_django.save()

    feb_python = PostFactory(
        owner=blog.owner,
        parent=blog,
        title="Python Weeknotes",
        slug="python-weeknotes",
        body=body,
        visible_date=timezone.make_aware(datetime(2026, 2, 20)),
    )
    feb_python.tags.add("python")
    feb_python.categories.add(weeknotes)
    feb_python.save()


@pytest.mark.django_db
def test_facet_counts_detail_mode_modal_schema(api_client, blog, post):
    category = PostCategory.objects.create(name="category", slug="category")
    post.categories.add(category)
    post.tags.add("tag")
    post.save()

    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})
    r = api_client.get(f"{url}?mode=modal", format="json")
    assert r.status_code == 200

    result = r.json()
    assert result["mode"] == "modal"
    assert isinstance(result["result_count"], int)
    assert set(result["groups"].keys()) == {"date_facets", "category_facets", "tag_facets"}

    for group in result["groups"].values():
        assert set(group.keys()) == {"selected", "all_count", "options"}
        assert isinstance(group["selected"], str)
        assert isinstance(group["all_count"], int)
        assert isinstance(group["options"], list)
        for option in group["options"]:
            assert set(option.keys()) == {"slug", "name", "count"}


@pytest.mark.django_db
def test_facet_counts_detail_excludes_restricted_post_facets(api_client, blog, post):
    post.tags.add("secret")
    post.save()
    PageViewRestriction.objects.create(page=post, restriction_type=PageViewRestriction.LOGIN)

    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})
    response = api_client.get(url, format="json")

    assert response.status_code == 200
    assert response.json()["facet_counts"]["tag_facets"] == []


@pytest.mark.django_db
def test_facet_counts_detail_modal_excludes_restricted_post_facets(api_client, blog, post):
    post.tags.add("secret")
    post.save()
    PageViewRestriction.objects.create(page=post, restriction_type=PageViewRestriction.LOGIN)

    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})
    response = api_client.get(f"{url}?mode=modal", format="json")

    assert response.status_code == 200
    result = response.json()
    assert result["result_count"] == 0
    assert result["groups"]["tag_facets"]["options"] == []


@pytest.mark.django_db
def test_facet_counts_detail_mode_modal_malformed_search_does_not_raise(api_client, blog, post):
    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})
    query_string = urlencode({"mode": "modal", "search": SCANNER_SEARCH_PAYLOAD})

    r = api_client.get(f"{url}?{query_string}", format="json")

    assert r.status_code == 200
    assert r.json()["mode"] == "modal"


@pytest.mark.django_db
def test_facet_counts_detail_unknown_mode_returns_legacy_response(api_client, blog, post):
    post.tags.add("tag")
    post.save()
    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})

    legacy = api_client.get(url, format="json")
    unknown_mode = api_client.get(f"{url}?mode=unknown", format="json")

    assert legacy.status_code == 200
    assert unknown_mode.status_code == 200
    assert unknown_mode.json() == legacy.json()


@pytest.mark.django_db
def test_facet_counts_detail_mode_modal_universe_merge_includes_zero_count_options(api_client, blog, body):
    _create_modal_facet_posts(blog, body)
    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})

    r = api_client.get(f"{url}?mode=modal&tag_facets=django&category_facets=weeknotes", format="json")
    assert r.status_code == 200
    result = r.json()

    assert result["result_count"] == 0
    date_counts = {option["slug"]: option["count"] for option in result["groups"]["date_facets"]["options"]}
    assert date_counts["2026-01"] == 0
    assert date_counts["2026-02"] == 0

    tag_counts = {option["slug"]: option["count"] for option in result["groups"]["tag_facets"]["options"]}
    assert tag_counts["django"] == 0
    assert tag_counts["python"] == 1


@pytest.mark.django_db
def test_facet_counts_detail_mode_modal_uses_own_group_exclusion(api_client, blog, body):
    _create_modal_facet_posts(blog, body)
    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})

    r = api_client.get(f"{url}?mode=modal&tag_facets=python&category_facets=til", format="json")
    assert r.status_code == 200
    result = r.json()

    assert result["result_count"] == 1
    assert result["groups"]["tag_facets"]["all_count"] == 2
    tag_counts = {option["slug"]: option["count"] for option in result["groups"]["tag_facets"]["options"]}
    assert tag_counts["python"] == 1
    assert tag_counts["django"] == 1


@pytest.mark.django_db
def test_facet_counts_detail_mode_modal_omits_groups_not_configured(api_client, blog, post, mocker):
    post.tags.add("tag")
    post.save()
    mocker.patch("cast.modal_facet_counts.appsettings.CAST_FILTERSET_FACETS", ["search", "tag_facets", "o"])

    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})
    r = api_client.get(f"{url}?mode=modal", format="json")
    assert r.status_code == 200
    assert set(r.json()["groups"].keys()) == {"tag_facets"}


@pytest.mark.django_db
def test_facet_counts_detail_mode_modal_empty_blog(api_client, blog):
    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})
    r = api_client.get(f"{url}?mode=modal", format="json")
    assert r.status_code == 200

    result = r.json()
    assert result["result_count"] == 0
    assert set(result["groups"].keys()) == {"date_facets", "category_facets", "tag_facets"}
    for group in result["groups"].values():
        assert group["all_count"] == 0
        assert group["selected"] == ""
        assert group["options"] == []


@pytest.mark.django_db
def test_facet_counts_detail_mode_modal_search_aggregation_path(api_client, blog, post, mocker):
    post.tags.add("python")
    post.save()
    mocker.patch("cast.modal_facet_counts._supports_aggregation_on_queryset", return_value=True)
    fallback_spy = mocker.spy(modal_facet_counts, "_queryset_from_pk_fallback")

    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})
    r = api_client.get(f"{url}?mode=modal&search={post.title}", format="json")
    assert r.status_code == 200
    assert fallback_spy.call_count == 0
    assert r.json()["mode"] == "modal"


@pytest.mark.django_db
def test_facet_counts_detail_mode_modal_search_aggregation_fallback_path(api_client, blog, post, mocker):
    post.tags.add("python")
    post.save()
    mocker.patch("cast.modal_facet_counts._supports_aggregation_on_queryset", return_value=False)
    fallback_spy = mocker.spy(modal_facet_counts, "_queryset_from_pk_fallback")

    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})
    r = api_client.get(f"{url}?mode=modal&search={post.title}", format="json")
    assert r.status_code == 200
    assert fallback_spy.call_count > 0
    assert r.json()["mode"] == "modal"


@pytest.mark.django_db
def test_facet_counts_detail_mode_modal_aggregation_probe_runs_once(api_client, blog, post, mocker):
    post.tags.add("python")
    post.save()
    probe_spy = mocker.spy(modal_facet_counts, "_supports_aggregation_on_queryset")

    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})
    r = api_client.get(f"{url}?mode=modal", format="json")
    assert r.status_code == 200
    assert probe_spy.call_count == 1


@pytest.mark.django_db
def test_facet_counts_detail_mode_modal_with_date_facets(api_client, blog, body):
    """Selecting a date_facets param filters posts to the matching month."""
    _create_modal_facet_posts(blog, body)
    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})

    r = api_client.get(f"{url}?mode=modal&date_facets=2026-01", format="json")
    assert r.status_code == 200
    result = r.json()
    assert result["result_count"] == 1
    assert result["groups"]["date_facets"]["selected"] == "2026-01"


@pytest.mark.django_db
@pytest.mark.parametrize("date_value", ["not-a-date", "2026-13", "abc"])
def test_facet_counts_detail_mode_modal_with_invalid_date_facets(api_client, blog, body, date_value):
    """Invalid date_facets param should be normalized to empty and not filter results."""
    _create_modal_facet_posts(blog, body)
    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})

    r = api_client.get(f"{url}?mode=modal&date_facets={date_value}", format="json")
    assert r.status_code == 200
    result = r.json()
    assert result["groups"]["date_facets"]["selected"] == ""
    # Invalid facet should not filter — result_count equals all posts
    assert result["result_count"] == 3


@pytest.mark.django_db
def test_facet_counts_detail_mode_modal_with_invalid_slug_facets(api_client, blog, body):
    """Invalid slug values should be normalized to empty and not filter results."""
    _create_modal_facet_posts(blog, body)
    url = reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})

    r = api_client.get(f"{url}?mode=modal&tag_facets=not+valid!", format="json")
    assert r.status_code == 200
    result = r.json()
    assert result["groups"]["tag_facets"]["selected"] == ""
    # Invalid facet should not filter — result_count equals all posts
    assert result["result_count"] == 3


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2026-01", "2026-01"),
        ("not-a-date", ""),
        ("2026-13", ""),
        ("", ""),
    ],
)
def test_normalize_date_facet(value, expected):
    from cast.modal_facet_counts import _normalize_date_facet

    assert _normalize_date_facet(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        ("valid-slug", "valid-slug"),
        ("invalid slug!", ""),
        ("has spaces", ""),
        ("", ""),
    ],
)
def test_normalize_slug_facet(value, expected):
    from cast.modal_facet_counts import _normalize_slug_facet

    assert _normalize_slug_facet(value) == expected


@pytest.mark.django_db
def test_supports_aggregation_on_queryset_exception(mocker):
    """When the aggregation probe raises, _supports_aggregation_on_queryset returns False."""
    from cast.modal_facet_counts import _supports_aggregation_on_queryset
    from cast.models import Post

    qs = Post.objects.none()
    original_order_by = qs.order_by

    def failing_order_by(*args, **kwargs):
        result = original_order_by(*args, **kwargs)
        mock_values = mocker.MagicMock()
        mock_values.annotate.return_value.__getitem__ = mocker.MagicMock(
            side_effect=Exception("simulated aggregation failure")
        )
        result.values = mocker.MagicMock(return_value=mock_values)
        return result

    mocker.patch.object(qs, "order_by", side_effect=failing_order_by)
    assert _supports_aggregation_on_queryset(qs) is False


@pytest.mark.django_db
def test_queryset_from_pk_fallback_empty():
    """When the input queryset is empty, _queryset_from_pk_fallback returns an empty queryset."""
    from cast.modal_facet_counts import _queryset_from_pk_fallback
    from cast.models import Post

    qs = Post.objects.none()
    result = _queryset_from_pk_fallback(qs)
    assert result.count() == 0


def test_date_rows_to_counts_skips_none_month():
    """When a row has month=None it should be silently skipped."""
    from cast.modal_facet_counts import _date_rows_to_counts

    rows = [
        (None, 3),
        (datetime(2026, 1, 1), 5),
    ]
    assert _date_rows_to_counts(rows) == {"2026-01": 5}
