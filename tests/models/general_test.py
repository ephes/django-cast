# ruff: noqa: F401,F811,I001
import os
from types import SimpleNamespace

import pytest
from django import forms
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError
from django.http import QueryDict
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from cast import appsettings
from cast.devdata import create_transcript
from cast.models import Audio, Blog, Contributor, ContributorLink, EpisodeContributor, File, Podcast, Season
from cast.models.contributors import ContributorLinkSelect
from cast.models.pages import (
    PODLOVE_POSTER_RENDITION_SPEC,
    SOCIAL_COVER_RENDITION_SPEC,
    CustomEpisodeForm,
    Episode,
    HomePage,
    HtmlField,
    Post,
)
from cast.models.repository import BlogIndexContext
from cast.models.transcript import Transcript
from cast.transcripts.dote import convert_dote_to_podcastindex_transcript, time_to_seconds
from cast.models.video import Video
from tests.factories import EpisodeFactory, PodcastFactory


def test_htmx_http_request_is_importable_from_neutral_module():
    """Models must not depend on the views package for typing (architecture review M1)."""
    from cast.http_types import HtmxHttpRequest as neutral
    from cast.views.htmx_helpers import HtmxHttpRequest as legacy

    assert neutral is legacy


class TestVideoModel:
    pytestmark = pytest.mark.django_db

    def test_get_all_video_paths(self, video):
        all_paths = list(video.get_all_paths())
        assert len(all_paths) == 1

    def test_get_all_video_paths_with_poster(self, video_with_poster):
        all_paths = list(video_with_poster.get_all_paths())
        assert len(all_paths) == 2

    def test_get_all_video_paths_without_original(self, video_without_original):
        assert video_without_original.get_all_paths() == set()

    def test_get_all_video_paths_without_thumbnail(self, video):
        class Dummy:
            name = "foobar"
            closed = True

            def open(self):
                return None

            def close(self):
                return None

            def seek(self, position):
                return None

            def read(self, num_bytes):
                return b""

            def tell(self):
                return 0

        video.poster = Dummy()
        all_paths = list(video.get_all_paths())
        assert len(all_paths) == 2


class TestGalleryModel:
    @pytest.mark.django_db
    def test_get_image_ids(self, gallery):
        assert len(gallery.image_ids) == gallery.images.count()


class TestFileModel:
    @pytest.mark.django_db
    def test_get_all_file_paths(self, file_instance):
        all_paths = list(file_instance.get_all_paths())
        assert len(all_paths) == 1

    @pytest.mark.django_db
    def test_get_all_file_paths_without_original(self, user):
        file_instance = File(user=user)

        assert file_instance.get_all_paths() == set()


@pytest.fixture()
def use_django_blog_index_repo():
    previous = appsettings.CAST_REPOSITORY
    appsettings.CAST_REPOSITORY = "django"
    yield appsettings.CAST_REPOSITORY
    appsettings.CAST_REPOSITORY = previous


class TestBlogModel:
    pytestmark = pytest.mark.django_db

    def test_blog_str(self, blog):
        assert blog.title == str(blog)

    def test_blog_author_null(self, blog):
        blog.author = None
        assert blog.author_name == blog.owner.get_full_name()

    def test_blog_author_not_null(self, blog):
        blog.author = "Foobar"
        assert blog.author_name == blog.author

    # def test_paginate_queryset_request_is_none(self, blog):
    #     context = blog.paginate_queryset({}, blog.get_filterset(QueryDict()).qs, QueryDict())
    #     assert context["page_number"] == 1

    def test_paginate_has_previous(self, blog):
        class Page:
            def has_previous(self):
                return True

            def previous_page_number(self):
                return 1

            def has_next(self):
                return True

            def next_page_number(self):
                return 2

        context = blog.get_next_and_previous_pages(Page())
        assert context["has_next"] is True
        assert context["next_page_number"] == 2
        assert context["has_previous"] is True
        assert context["previous_page_number"] == 1

    def test_wagtail_api_pages_url(self, blog):
        assert blog.wagtail_api_pages_url == "/cast/api/wagtail/pages/"

    def test_pagination_page_size(self, blog):
        assert blog.pagination_page_size == appsettings.POST_LIST_PAGINATION

    def test_facet_counts_api_url(self, blog):
        assert blog.facet_counts_api_url == reverse("cast:api:facet-counts-detail", kwargs={"pk": blog.pk})

    def test_theme_list_api_url(self, blog):
        assert blog.theme_list_api_url == reverse("cast:api:theme-list")

    def test_theme_update_api_url(self, blog):
        assert blog.theme_update_api_url == reverse("cast:api:theme-update")

    def test_player_config_api_url(self, blog):
        assert blog.podlove_player_config_url == reverse("cast:api:player_config")

    def test_comment_post_url(self, blog):
        assert blog.comment_post_url == reverse("comments-post-comment-ajax")

    def test_comments_security_data_for_open_comments(self, post, comments_enabled):
        security_data = post.comments_security_data

        assert security_data["content_type"] == "cast.post"
        assert security_data["object_pk"] == str(post.pk)
        assert "timestamp" in security_data
        assert "security_hash" in security_data

    def test_has_selectable_themes(self, blog, simple_request):
        assert blog.get_context(simple_request)["has_selectable_themes"]

    def test_template_base_dir_is_none(self, blog, simple_request):
        template = blog.get_template(simple_request, template_base_dir="foobar")
        assert template == "cast/foobar/blog_list_of_posts.html"

    def test_get_django_repository(self, blog, simple_request, use_django_blog_index_repo):
        repository = blog.get_repository(simple_request, {})
        assert isinstance(repository, BlogIndexContext)

    def test_last_build_date_without_published_posts_falls_back_to_first_published_at(self, blog):
        blog.first_published_at = timezone.now() - timezone.timedelta(days=1)
        assert blog.last_build_date == blog.first_published_at

    def test_last_build_date_without_published_posts_or_first_published_at_falls_back_to_now(self, blog):
        blog.first_published_at = None
        before = timezone.now()
        result = blog.last_build_date
        after = timezone.now()
        assert before <= result <= after

    def test_get_cover_image_url_for_blog(self, mocker):
        # just empty cover image
        blog = Blog(id=1)
        assert blog.get_cover_image_context() == {"cover_image_url": "", "cover_alt_text": ""}

        # cover image via blog.cover_image - using mock object because of the ImageField setter
        mock_image = mocker.MagicMock()
        mock_image.file.url = "https://example.org/cover.jpg"
        mocker.patch("cast.models.Blog.cover_image", mock_image)
        assert blog.get_cover_image_context() == {
            "cover_image_url": "https://example.org/cover.jpg",
            "cover_alt_text": "",
        }


class TestPodcastModel:
    def test_cover_image_from_super(self, mocker):
        podcast = Podcast(id=1)
        mocker_image = mocker.MagicMock()
        mocker_image.file.url = "https://example.org/cover.jpg"
        mocker.patch("cast.models.Blog.cover_image", mocker_image)
        assert podcast.get_cover_image_context() == {
            "cover_image_url": "https://example.org/cover.jpg",
            "cover_alt_text": "",
        }

    def test_podcast_get_context(self, rf, mocker):
        mocker.patch("cast.models.Blog.get_context", return_value={})
        request = rf.get("/")
        podcast = Podcast(id=1)
        context = podcast.get_context(request)
        assert context["podcast"] == podcast

    def test_itunes_type_is_optional(self):
        podcast = Podcast(id=1, title="Podcast", slug="podcast", itunes_type="")

        Podcast._meta.get_field("itunes_type").clean(podcast.itunes_type, podcast)

    @pytest.mark.parametrize("itunes_type", ["episodic", "serial"])
    def test_itunes_type_choices_are_valid(self, itunes_type):
        podcast = Podcast(id=1, title="Podcast", slug="podcast", itunes_type=itunes_type)

        Podcast._meta.get_field("itunes_type").clean(podcast.itunes_type, podcast)

    def test_itunes_type_rejects_unknown_value(self):
        podcast = Podcast(id=1, title="Podcast", slug="podcast", itunes_type="chronological")

        with pytest.raises(ValidationError) as error:
            Podcast._meta.get_field("itunes_type").clean(podcast.itunes_type, podcast)

        assert error.value.code == "invalid_choice"


class TestSeasonModel:
    pytestmark = pytest.mark.django_db

    def test_season_ordering_and_str(self, podcast):
        second = Season.objects.create(podcast=podcast, number=2, name="Second season")
        first = Season.objects.create(podcast=podcast, number=1)

        assert list(podcast.seasons.values_list("number", flat=True)) == [1, 2]
        assert str(first) == f"{podcast.title}: Season 1"
        assert str(second) == f"{podcast.title}: Season 2 - Second season"

    def test_season_str_without_podcast(self):
        season = Season(number=3)

        assert str(season) == "Podcast: Season 3"

    def test_season_number_is_required_to_be_positive(self, podcast):
        season = Season(podcast=podcast, number=0)

        with pytest.raises(ValidationError) as error:
            season.full_clean()

        assert "number" in error.value.error_dict

    def test_season_number_is_unique_per_podcast(self, podcast):
        Season.objects.create(podcast=podcast, number=1)

        with pytest.raises(IntegrityError), transaction.atomic():
            Season.objects.create(podcast=podcast, number=1)
