from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from cast.api.views import (
    AudioPodloveDetailView,
    FilteredPagesAPIViewSet,
    ThemeListView,
)
from cast.models import PostCategory

from .factories import UserFactory


def test_api_root(api_client):
    """Test that the API root returns a 200."""
    url = reverse("cast:api:root")
    r = api_client.get(url)
    assert r.status_code == 200


class TestBlogVideo:
    pytestmark = pytest.mark.django_db

    @classmethod
    def setup_class(cls):
        cls.list_url = reverse("cast:api:video_list")
        cls.detail_url = reverse("cast:api:video_detail", kwargs={"pk": 1})

    def test_video_list_endpoint_without_authentication(self, api_client):
        """Check for not authenticated status code if trying to access the list
        endpoint without being authenticated.
        """
        r = api_client.get(self.list_url, format="json")
        assert r.status_code == 403

    def test_video_detail_endpoint_without_authentication(self, api_client):
        """Check for not authenticated status code if trying to access the
        detail endpoint without being authenticated.
        """
        r = api_client.get(self.detail_url, format="json")
        assert r.status_code == 403

    def test_video_list_endpoint_with_authentication(self, api_client):
        """Check for list result when accessing the list endpoint
        being logged in.
        """
        user = UserFactory()
        api_client.login(username=user.username, password="password")
        r = api_client.get(self.list_url, format="json")
        # dont redirect to login page
        assert r.status_code == 200
        assert "results" in r.json()


class TestBlogAudio:
    pytestmark = pytest.mark.django_db

    @classmethod
    def setup_class(cls):
        cls.list_url = reverse("cast:api:audio_list")
        cls.detail_url = reverse("cast:api:audio_detail", kwargs={"pk": 1})

    def test_audio_list_endpoint_without_authentication(self, api_client):
        """Check for not authenticated status code if trying to access the list
        endpoint without being authenticated.
        """
        r = api_client.get(self.list_url, format="json")
        assert r.status_code == 403

    def test_audio_detail_endpoint_without_authentication(self, api_client):
        """Check for not authenticated status code if trying to access the
        detail endpoint without being authenticated.
        """
        r = api_client.get(self.detail_url, format="json")
        assert r.status_code == 403

    def test_audio_list_endpoint_with_authentication(self, api_client):
        """Check for list result when accessing the list endpoint
        being logged in.
        """
        user = UserFactory()
        api_client.login(username=user.username, password="password")
        r = api_client.get(self.list_url, format="json")
        # dont redirect to login page
        assert r.status_code == 200
        assert "results" in r.json()


class TestPodcastAudio:
    pytestmark = pytest.mark.django_db

    def test_podlove_detail_endpoint_without_authentication(self, api_client, audio):
        """Should be accessible without authentication."""
        podlove_detail_url = reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk})
        r = api_client.get(podlove_detail_url, format="json")
        assert r.status_code == 200

    def test_podlove_detail_endpoint_duration(self, api_client, audio):
        """Test whether microseconds get stripped away from duration via api - they have
        to be for podlove player to work.
        """
        delta = timedelta(days=0, hours=1, minutes=10, seconds=20, microseconds=40)
        audio.duration = delta
        audio.save()
        assert "." in str(audio.duration)
        podlove_detail_url = reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk})
        r = api_client.get(podlove_detail_url, format="json")
        assert "." not in r.json()["duration"]

    def test_podlove_detail_endpoint_includes_link_to_episode(self, api_client, episode):
        """Test whether the podlove detail endpoint includes a link to the episode."""
        audio = episode.podcast_audio
        podlove_detail_url = reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk})

        r = api_client.get(podlove_detail_url, format="json")
        assert r.status_code == 200

        # link is always included, might be empty
        assert "link" in r.json()

        # explicitly set episode_id FIXME: only works if there are multiple episodes for audio
        podlove_detail_url_with_episode_id = f"{podlove_detail_url}?episode_id={episode.pk}"

        r = api_client.get(podlove_detail_url_with_episode_id, format="json")
        assert r.status_code == 200

        podlove_data = r.json()
        assert "link" in podlove_data
        assert podlove_data["link"] == episode.full_url

    def test_podlove_detail_endpoint_chaptermarks(self, api_client, audio, chaptermarks):
        """Test whether chaptermarks get delivered via podlove endpoint."""
        podlove_detail_url = reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk})
        r = api_client.get(podlove_detail_url, format="json")
        chapters = r.json()["chapters"]
        for chapter in chapters:
            # assert microseconds are stripped away
            assert "." not in chapter["start"]
            assert ":" in chapter["start"]
        assert len(chapters) == 3
        # assert reordering
        assert chapters[-1]["title"] == "coughing"

    def test_podlove_detail_retrieve_with_value_error(self, mocker):
        class MockRequest:
            query_params = {"episode_id": "foo"}

        mocker.patch("cast.api.views.AudioPodloveDetailView.get_object")
        mocker.patch("cast.api.views.AudioPodloveDetailView.get_serializer")
        podlove_view = AudioPodloveDetailView()
        response = podlove_view.retrieve(MockRequest())
        assert response.status_code == 200


class TestCommentTrainingData:
    pytestmark = pytest.mark.django_db

    @classmethod
    def setup_class(cls):
        cls.url = reverse("cast:api:comment-training-data")

    def test_get_comment_training_data_without_authentication(self, api_client):
        """Should not be accessible without authentication."""
        r = api_client.get(self.url, format="json")
        assert r.status_code == 403

    def test_get_comment_training_data_with_authentication(self, api_client):
        """Check for list result when accessing the training data endpoint being logged in."""
        user = UserFactory()
        api_client.login(username=user.username, password="password")
        r = api_client.get(self.url, format="json")
        assert r.status_code == 200
        assert r.json() == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    "date, post_filter, len_result",
    [
        (timezone.datetime(2022, 8, 22), "true", 0),  # wrong date facet -> not found
        (timezone.now(), "true", 1),  # correct date facet -> found
        (timezone.datetime(2022, 8, 22), "false", 1),  # wrong date facet and no post filter -> found
    ],
)
def test_wagtail_pages_api_with_post_filter(date, post_filter, len_result, rf, blog, post):
    viewset = FilteredPagesAPIViewSet()
    path = blog.wagtail_api_pages_url
    date_facet = f"{date.year}-{date.month}"
    request = rf.get(
        f"{path}?child_of={blog.pk}&type=cast.Post&date_facets={date_facet}&use_post_filter={post_filter}"
    )
    viewset.request = request
    queryset = viewset.get_queryset()
    assert len(queryset) == len_result


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
def test_facet_counts_list(api_client, blog):
    """
    Test whether the facet counts list endpoint returns a list of all blogs
    and the blog is included in the result.
    """
    url = reverse("cast:api:facet-counts-list")
    r = api_client.get(url, format="json")
    assert r.status_code == 200

    [result] = r.json()["results"]
    assert "id" in result
    assert "url" in result
    assert result["id"] == blog.pk


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
    assert facet_counts["date_facets"][0]["slug"] == post.visible_date.strftime("%Y-%m")
    assert facet_counts["date_facets"][0]["name"] == post.visible_date.strftime("%Y-%m")
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
def test_get_comments_via_post_detail(api_client, post, comment):
    url = reverse("cast:api:wagtail:pages:detail", kwargs={"pk": post.pk})
    r = api_client.get(url, format="json")
    assert r.status_code == 200

    comments = r.json()["comments"]
    assert comments[0]["comment"] == comment.comment


def test_theme_list_queryset_is_none():
    view = ThemeListView()
    assert view.get_queryset() is None


@pytest.mark.django_db
def test_list_themes(api_client):
    # Given an api url to fetch the list of themes
    url = reverse("cast:api:theme-list")
    # When we request the list of themes
    r = api_client.get(url, format="json")
    assert r.status_code == 200

    # Then we expect a list of themes to be returned and include the `plain` theme
    result = r.json()
    assert "plain" in {theme["slug"] for theme in result["items"]}


@pytest.mark.django_db
def test_update_theme(api_client):
    # Given an api url to update the theme
    url = reverse("cast:api:theme-update")
    # When we post to the update theme endpoint
    r = api_client.post(url, {"theme_slug": "plain"}, format="json")
    assert r.status_code == 200

    # Then we expect a success message to be returned
    result = r.json()
    assert result["message"] == "Theme updated successfully"
    assert api_client.session.get("template_base_dir") == "plain"


@pytest.mark.django_db
def test_update_theme_invalid(api_client):
    # Given an api url to update the theme
    url = reverse("cast:api:theme-update")
    # When we post an invalid theme to the update theme endpoint
    r = api_client.post(url, {"theme_slug": "invalid"}, format="json")
    assert r.status_code == 400

    # Then we expect an error message to be returned and
    # the theme is not stored in the session
    result = r.json()
    print(result)
    assert result["error"] == "Theme slug is invalid"
    assert api_client.session.get("template_base_dir") is None
