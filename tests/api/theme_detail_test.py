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


@pytest.mark.django_db
def test_get_comments_via_post_detail(api_client, post, comment):
    url = reverse("cast:api:wagtail:pages:detail", kwargs={"pk": post.pk})
    r = api_client.get(url, format="json")
    assert r.status_code == 200

    comments = r.json()["comments"]
    assert comments[0]["comment"] == comment.comment


@pytest.mark.django_db
def test_page_detail_omits_comment_security_data_when_comments_closed(api_client, post, comments_enabled):
    post.comments_enabled = False
    post.save()
    url = reverse("cast:api:wagtail:pages:detail", kwargs={"pk": post.pk})

    response = api_client.get(url, format="json")

    assert response.status_code == 200
    assert response.json()["comments_security_data"] == {}


@pytest.mark.django_db
def test_wagtail_api_page_detail_includes_cover_image_poster_url(api_client, post, image, mocker):
    mock_rendition = mocker.MagicMock(url="/media/podlove.jpg")
    mocker.patch("wagtail.images.models.Image.get_rendition", return_value=mock_rendition)
    post.cover_image = image
    post.save()
    url = reverse("cast:api:wagtail:pages:detail", kwargs={"pk": post.pk})
    r = api_client.get(url, format="json")
    assert r.status_code == 200

    assert r.json()["cover_image_poster_url"] == "http://testserver" + mock_rendition.url


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
    assert all(t.name.startswith("cast/plain/") or t.name == "wagtailcore/shared/richtext.html" for t in r.templates)
