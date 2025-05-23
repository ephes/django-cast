import json
from datetime import datetime, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from cast.api.serializers import AudioPodloveSerializer
from cast.api.views import (
    AudioPodloveDetailView,
    CastImagesAPIViewSet,
    FilteredPagesAPIViewSet,
    ThemeListView,
)
from cast.devdata import generate_blog_with_media
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

    def test_podlove_podlove_detail_endpoint_show_metadata_without_artwork(self, api_client, episode):
        """Test whether the podlove detail endpoint includes show metadata, but no artwork."""
        audio = episode.podcast_audio
        podlove_detail_url = reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk, "post_id": episode.pk})

        r = api_client.get(podlove_detail_url, format="json")
        assert r.status_code == 200

        podlove_data = r.json()
        podcast = episode.blog.specific
        assert "show" in podlove_data
        assert podlove_data["show"]["title"] == podcast.title
        assert podlove_data["show"]["subtitle"] == podcast.subtitle
        assert podlove_data["show"]["poster"] == ""
        assert podlove_data["show"]["link"] == podcast.full_url

    def test_podlove_podlove_detail_endpoint_show_metadata_with_cover_image(self, image, episode):
        serializer = AudioPodloveSerializer(context={"post": episode})
        episode.cover_image = image
        metadata = serializer.get_show(episode.podcast_audio)
        assert metadata["poster"] == image.file.url

    def test_podlove_podlove_detail_endpoint_show_metadata(
        self, api_client, image, episode_with_podcast_with_cover_image
    ):
        """Test whether the podlove detail endpoint includes show metadata."""
        episode = episode_with_podcast_with_cover_image
        audio = episode.podcast_audio
        podcast = episode.blog.specific

        podlove_detail_url = reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk, "post_id": episode.pk})
        r = api_client.get(podlove_detail_url, format="json")
        assert r.status_code == 200

        podlove_data = r.json()
        assert "show" in podlove_data
        assert podlove_data["show"]["title"] == podcast.title
        assert podlove_data["show"]["subtitle"] == podcast.subtitle
        assert podlove_data["show"]["poster"] == podcast.cover_image.file.url
        assert podlove_data["show"]["link"] == podcast.full_url

    def test_podlove_player_config(self, api_client):
        """Test whether the podlove player config endpoint returns the player config."""
        url = reverse("cast:api:player_config")
        response = api_client.get(url, format="json")
        assert response.status_code == 200
        config = response.json()
        assert "activeTab" in config

    def test_audio_podlove_serializer_get_transcripts(self, mocker):
        """Test whether the audio podlove serializer returns the correct transcripts."""
        # Given an episode without transcripts
        episode = mocker.MagicMock()
        episode.podcast_audio = None
        serializer = AudioPodloveSerializer(context={"post": episode})
        # When we call the get_transcripts method, then we expect an empty list
        assert serializer.get_transcripts(episode.podcast_audio) == []

        # Given an episode with an audio with a transcript without a podlove file
        # When we call the get_transcripts method, then we expect an empty list
        audio = mocker.MagicMock()
        audio.transcript = mocker.MagicMock()
        audio.transcript.podlove = None
        assert serializer.get_transcripts(audio) == []

        # Given an episode with an audio with a transcript with a podlove file containing valid JSON
        mock_file = mocker.MagicMock()
        mock_file.__enter__.return_value = mock_file
        mock_file.read.return_value = json.dumps({"transcripts": [{"text": "Hello"}]})

        mock_podlove = mocker.MagicMock()
        mock_podlove.open.return_value = mock_file

        transcript = mocker.MagicMock()
        transcript.podlove = mock_podlove

        audio = mocker.MagicMock()
        audio.transcript = transcript

        # When we call the get_transcripts method, then we expect the transcripts to be returned
        result = serializer.get_transcripts(audio)
        assert result == [{"text": "Hello"}]

        # Given an invalid key for the transcripts
        mock_file.read.return_value = json.dumps({"invalid_key": [{"text": "Hello"}]})

        # When we call the get_transcripts method, then we expect an empty list
        assert serializer.get_transcripts(audio) == []

        # Given invalid JSON in the podlove file
        mock_file.read.return_value = "{ invalid json }"

        # When we call the get_transcripts method, then we expect an empty list
        assert serializer.get_transcripts(audio) == []


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
        (datetime(2022, 8, 22), "true", 0),  # wrong date facet -> not found
        (timezone.now(), "true", 1),  # correct date facet -> found
        (datetime(2022, 8, 22), "false", 1),  # wrong date facet and no post filter -> found
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

    [result] = r.json()["results"]
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


@pytest.mark.django_db
def test_wagtail_api_page_detail_with_chooser_happy(api_client):
    """
    Access the wagtail api page detail endpoint with a post that has an image
    or video. This did throw a 500 error before -> sentry saw it -> fix it.
    """
    blog = generate_blog_with_media(media_numbers={"images": 1, "videos": 1, "galleries": 1})
    post = blog.unfiltered_published_posts.first()
    url = reverse("cast:api:wagtail:pages:detail", kwargs={"pk": post.pk})
    r = api_client.get(url, format="json")
    assert r.status_code == 200


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
    assert result["error"] == "Theme slug is invalid"
    assert api_client.session.get("template_base_dir") is None


def test_update_theme_int_payload(api_client):
    # Given an api url to update the theme
    url = reverse("cast:api:theme-update")
    # When we post an integer payload to the update theme endpoint
    r = api_client.post(url, 23, format="json")
    assert r.status_code == 400

    # Then we expect an error message to be returned and
    # the theme is not stored in the session
    result = r.json()
    assert result["error"] == "Invalid request"


@pytest.mark.django_db
def test_render_html_with_theme_from_session(api_client, post):
    # Given we have custom theme set in the session
    r = api_client.post(
        # FIXME there's some way to update the session more elegantly
        # use this instead of the post request
        reverse("cast:api:theme-update"),
        {"theme_slug": "plain"},
        format="json",
    )
    assert r.status_code == 200

    # When we request the blog post via api
    url = reverse("cast:api:wagtail:pages:detail", kwargs={"pk": post.pk})
    r = api_client.get(url, format="json")
    assert r.status_code == 200

    # Then we expect the blog post to be rendered with the theme from the session
    assert r.context.get("template_base_dir") == "plain"
    assert all([t.name.startswith("cast/plain/") for t in r.templates])
