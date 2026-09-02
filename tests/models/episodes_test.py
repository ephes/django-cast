# ruff: noqa: F401,F811,I001
import json
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
from cast.media_derivation import save_video_with_derivations
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


class TestEpisodeModel:
    pytestmark = pytest.mark.django_db

    def test_get_context_without_absolute_url(self, mocker):
        class Request:
            pass

        mocker.patch("cast.models.Post.get_context", return_value={})
        episode = Episode()
        context = episode.get_context(Request())
        assert "player_url" not in context

    def test_get_enclosure_size_podcast_is_none(self):
        episode = Episode()
        assert episode.get_enclosure_size("mp3") == 0

    @pytest.mark.parametrize(
        "local_template_name, expected_template",
        [
            (None, "cast/bootstrap4/episode.html"),
            ("foobar.html", "cast/bootstrap4/foobar.html"),
        ],
    )
    def test_get_template_for_episode(self, local_template_name, expected_template, mocker, simple_request):
        class TemplateBaseDirectory:
            name = "bootstrap4"

        mocker.patch("cast.models.pages.TemplateBaseDirectory.for_request", return_value=TemplateBaseDirectory())
        episode = Episode()
        kwargs = {} if local_template_name is None else {"local_template_name": local_template_name}

        assert episode.get_template(simple_request, **kwargs) == expected_template

    def test_page_type(self):
        episode = Episode()
        assert episode.page_type == "cast.Episode"

    def test_publishing_metadata_is_optional(self, episode):
        episode.episode_number = None
        episode.episode_type = ""
        episode.season = None

        episode.full_clean()

    @pytest.mark.parametrize("episode_type", ["full", "trailer", "bonus"])
    def test_episode_type_choices_are_valid(self, episode, episode_type):
        episode.episode_type = episode_type

        episode.full_clean()

    def test_episode_type_rejects_unknown_value(self, episode):
        episode.episode_type = "preview"

        with pytest.raises(ValidationError) as error:
            episode.full_clean()

        assert "episode_type" in error.value.error_dict

    def test_episode_number_is_required_to_be_positive(self, episode):
        episode.episode_number = 0

        with pytest.raises(ValidationError) as error:
            episode.full_clean()

        assert "episode_number" in error.value.error_dict

    def test_episode_accepts_season_from_same_podcast(self, episode):
        season = Season.objects.create(podcast=episode.podcast, number=1, name="Launch")
        episode.season = season

        episode.full_clean()

    def test_episode_rejects_season_from_different_podcast(self, episode, site):
        other_podcast = PodcastFactory(
            owner=episode.owner,
            parent=site.root_page,
            title="other podcast",
            slug="other-podcast",
        )
        other_season = Season.objects.create(podcast=other_podcast, number=1)
        episode.season = other_season

        with pytest.raises(ValidationError) as error:
            episode.full_clean()

        assert "season" in error.value.error_dict

    def test_parentless_episode_defers_season_podcast_validation(self, podcast):
        season = Season.objects.create(podcast=podcast, number=1)
        episode = Episode(title="Draft episode", slug="draft-episode", season=season)

        episode.clean()

    def test_blog_cache_validates_unsaved_episode_season(self, podcast, site):
        other_podcast = PodcastFactory(
            owner=podcast.owner,
            parent=site.root_page,
            title="other podcast",
            slug="other-podcast",
        )
        other_season = Season.objects.create(podcast=other_podcast, number=1)
        episode = Episode(title="Draft episode", slug="draft-episode", season=other_season)
        episode._blog = podcast

        with pytest.raises(ValidationError) as error:
            episode.clean()

        assert "season" in error.value.error_dict

    def test_season_validation_defers_when_blog_lookup_fails(self, mocker, podcast):
        season = Season.objects.create(podcast=podcast, number=1)
        episode = Episode(title="Draft episode", slug="draft-episode", season=season)
        mocker.patch.object(episode, "get_parent", side_effect=ValueError)

        episode._validate_season_matches_podcast()

    def test_season_validation_defers_when_blog_has_no_pk(self, podcast):
        season = Season.objects.create(podcast=podcast, number=1)
        episode = Episode(title="Draft episode", slug="draft-episode", season=season)
        episode._blog = Blog()

        episode.clean()

    def test_episode_form_limits_seasons_to_parent_podcast(self, episode, site):
        current_season = Season.objects.create(podcast=episode.podcast, number=1)
        other_podcast = PodcastFactory(
            owner=episode.owner,
            parent=site.root_page,
            title="another podcast",
            slug="another-podcast",
        )
        other_season = Season.objects.create(podcast=other_podcast, number=1)
        form_class = Episode.get_edit_handler().get_form_class()

        form = form_class(instance=episode)

        assert list(form.fields["season"].queryset) == [current_season]
        assert other_season not in form.fields["season"].queryset

    def test_episode_form_limits_seasons_to_add_parent_podcast(self, podcast, site):
        current_season = Season.objects.create(podcast=podcast, number=1)
        other_podcast = PodcastFactory(
            owner=podcast.owner,
            parent=site.root_page,
            title="new other podcast",
            slug="new-other-podcast",
        )
        other_season = Season.objects.create(podcast=other_podcast, number=1)
        form_class = Episode.get_edit_handler().get_form_class()

        form = form_class(instance=Episode(title="Draft episode", slug="draft-episode"), parent_page=podcast)

        assert list(form.fields["season"].queryset) == [current_season]
        assert other_season not in form.fields["season"].queryset

    def test_episode_form_keeps_all_seasons_when_parent_is_unknown(self, podcast):
        season = Season.objects.create(podcast=podcast, number=1)
        form_class = Episode.get_edit_handler().get_form_class()

        form = form_class(instance=Episode(title="Draft episode", slug="draft-episode"))

        assert list(form.fields["season"].queryset) == [season]

    def test_get_transcript_or_none_repository_none(self):
        episode = Episode(id=1)
        assert episode.get_transcript_or_none(None) is None

    def test_transcript_properties(self, episode):
        assert episode.transcript is None
        assert episode.has_transcript is False
        create_transcript(audio=episode.podcast_audio, podlove={"transcripts": [{"start": "00:00:00.000"}]})
        episode.refresh_from_db()
        assert episode.transcript is not None
        assert episode.has_transcript is True

    def test_get_transcript_url(self, episode):
        expected = reverse(
            "cast:episode-transcript",
            kwargs={"blog_slug": episode.blog.slug, "episode_slug": episode.slug},
        )
        assert episode.get_transcript_url() == expected

    def test_get_context_sets_transcript_url_without_absolute_uri(self, episode, mocker):
        class Request:
            pass

        create_transcript(audio=episode.podcast_audio, podlove={"transcripts": [{"start": "00:00:00.000"}]})
        episode.podcast_audio.refresh_from_db()
        repository = mocker.MagicMock()
        repository.blog.slug = episode.blog.slug
        mocker.patch(
            "cast.models.Post.get_context",
            return_value={"repository": repository, "render_for_feed": False},
        )
        context = episode.get_context(Request())
        expected = reverse(
            "cast:episode-transcript",
            kwargs={"blog_slug": episode.blog.slug, "episode_slug": episode.slug},
        )
        assert context["episode_transcript_url"] == expected

    def test_unpublished_episode_preview_omits_live_only_transcript_url(self, rf, client, episode):
        create_transcript(audio=episode.podcast_audio, podlove={"transcripts": [{"start": "00:00:00.000"}]})
        episode.unpublish()
        episode.refresh_from_db()

        context = episode.get_preview_context(rf.get("/"), "")

        assert context["render_detail"] is True
        assert "episode_transcript_url" not in context
        url = reverse(
            "cast:episode-transcript",
            kwargs={"blog_slug": episode.blog.slug, "episode_slug": episode.slug},
        )
        assert client.get(url).status_code == 404

    def test_get_vtt_transcript_url_no_transcript(self, rf, mocker):
        episode = Episode(id=1)
        request = rf.get("/")
        repository = mocker.MagicMock()
        repository.transcript.vtt = None
        assert episode.get_vtt_transcript_url(request, repository) is None

    def test_get_vtt_transcript_url_includes_episode_context(self, rf, episode):
        transcript = create_transcript(audio=episode.podcast_audio, vtt="WEBVTT\n\n")
        request = rf.get("/")

        url = episode.get_vtt_transcript_url(request, None)

        expected = reverse("cast:webvtt-transcript", kwargs={"pk": transcript.pk})
        assert url == request.build_absolute_uri(f"{expected}?episode_id={episode.pk}")

    def test_get_podcastindex_transcript_url_no_transcript(self, rf, mocker):
        episode = Episode(id=1)
        request = rf.get("/")
        repository = mocker.MagicMock()
        repository.transcript.dote = None
        assert episode.get_podcastindex_transcript_url(request, repository) is None

    def test_get_podcastindex_transcript_url_includes_episode_context(self, rf, episode):
        transcript = create_transcript(
            audio=episode.podcast_audio,
            dote={"lines": [{"startTime": "00:00:00,000", "endTime": "00:00:01,000", "text": "Hello"}]},
        )
        request = rf.get("/")

        url = episode.get_podcastindex_transcript_url(request, None)

        expected = reverse("cast:podcastindex-transcript-json", kwargs={"pk": transcript.pk})
        assert url == request.build_absolute_uri(f"{expected}?episode_id={episode.pk}")


@pytest.mark.django_db
def test_custom_episode_form():
    # arrange the custom episode form
    CustomEpisodeForm._meta.model = Episode
    CustomEpisodeForm._meta.fields = ("podcast_audio", "about_to_be_published")
    CustomEpisodeForm.formsets = {}

    # test the form with no data
    form = CustomEpisodeForm()
    assert not form.is_valid()

    assert "action-publish" not in form.fields

    # test the form with the "Save draft" button clicked (no audio file is ok)
    form = CustomEpisodeForm({"podcast_audio": None})
    assert form.is_valid()

    # test the form with the "Publish" button clicked (audio file is required)
    form = CustomEpisodeForm({"action-publish": "action-publish", "podcast_audio": None})
    form.fields["podcast_audio"] = forms.IntegerField(required=False)
    assert not form.is_valid()

    # tolerate duplicate publish values without rendering a hidden field that can shadow Wagtail's submit button
    form = CustomEpisodeForm(QueryDict("action-publish=action-publish&action-publish=&podcast_audio="))
    form.fields["podcast_audio"] = forms.IntegerField(required=False)
    assert not form.is_valid()


@pytest.mark.django_db
def test_episode_edit_view_publish_action_publishes_contributor_assignments(admin_client, episode):
    contributor = Contributor.objects.create(display_name="Published Guest", slug="published-guest")
    edit_url = reverse("wagtailadmin_pages:edit", args=(episode.pk,))
    post_data = {
        "action-publish": "action-publish",
        "title": episode.title,
        "slug": episode.slug,
        "visible_date": timezone.localtime(episode.visible_date).strftime("%Y-%m-%d %H:%M"),
        "podcast_audio": str(episode.podcast_audio_id),
        "body-count": "1",
        "body-0-deleted": "",
        "body-0-order": "0",
        "body-0-type": "overview",
        "body-0-value-count": "1",
        "body-0-value-0-deleted": "",
        "body-0-value-0-order": "0",
        "body-0-value-0-type": "paragraph",
        "body-0-value-0-value": json.dumps(
            {
                "blocks": [
                    {
                        "key": "00000",
                        "text": "Published overview",
                        "type": "header-two",
                        "depth": 0,
                        "inlineStyleRanges": [],
                        "entityRanges": [],
                        "data": {},
                    }
                ],
                "entityMap": {},
            }
        ),
        "keywords": "",
        "explicit": "1",
        "cover_image": "",
        "cover_alt_text": "",
        "tags": "",
        "seo_title": "",
        "search_description": "",
        "go_live_at": "",
        "expire_at": "",
        "comments-TOTAL_FORMS": "0",
        "comments-INITIAL_FORMS": "0",
        "comments-MIN_NUM_FORMS": "0",
        "comments-MAX_NUM_FORMS": "1000",
        "contributor_assignments-TOTAL_FORMS": "1",
        "contributor_assignments-INITIAL_FORMS": "0",
        "contributor_assignments-MIN_NUM_FORMS": "0",
        "contributor_assignments-MAX_NUM_FORMS": "1000",
        "contributor_assignments-0-contributor": str(contributor.pk),
        "contributor_assignments-0-role": EpisodeContributor.ROLE_GUEST,
        "contributor_assignments-0-link": "",
        "contributor_assignments-0-ORDER": "0",
        "contributor_assignments-0-id": "",
    }

    response = admin_client.post(edit_url, post_data)

    assert response.status_code == 302
    episode.refresh_from_db()
    assert episode.live is True
    assert episode.contributor_assignments.get().contributor == contributor
    live_episode = episode.live_revision.as_object()
    assert [assignment.contributor for assignment in live_episode.contributor_assignments.all()] == [contributor]


@pytest.mark.django_db
def test_homepage_serve(episode, mocker):
    mocker.patch("cast.models.pages.Page.serve", return_value="foobar")
    homepage = HomePage()

    # without alias
    assert homepage.serve(None) == "foobar"

    # with alias
    homepage.alias_for_page = episode
    r = homepage.serve(None)
    assert r.status_code == 302


@pytest.mark.django_db
def test_video_create_poster_video_url_without_http(mocker, tmp_path):
    tmp_poster = tmp_path / "poster.jpg"

    def fake_mkstemp(prefix, suffix):
        assert prefix == "poster_"
        assert suffix == ".jpg"
        return os.open(tmp_poster, os.O_CREAT | os.O_RDWR), str(tmp_poster)

    mocker.patch("cast.models.video.tempfile.mkstemp", side_effect=fake_mkstemp)
    mocker.patch("cast.models.video.Video._get_video_dimensions", return_value=(1, 1))
    run = mocker.patch("cast.models.video.subprocess.run", side_effect=ValueError())

    class Original:
        url = "https://example.com/video.mp4"

    video = Video()
    mocker.patch.object(video, "original", Original())
    with pytest.raises(ValueError):
        video._create_poster()
    call_kwargs = run.call_args_list[0]
    command = call_kwargs.args[0]
    assert command[0] == "ffmpeg"
    assert "https://example.com/video.mp4" in command
    assert call_kwargs.kwargs.get("check") is True
    assert call_kwargs.kwargs.get("timeout") == 30


@pytest.mark.django_db
def test_video_create_poster_closes_mkstemp_fd_and_removes_temp_file(mocker, tmp_path):
    tmp_poster = tmp_path / "poster.jpg"
    created_fd: int | None = None

    def fake_mkstemp(prefix, suffix):
        nonlocal created_fd
        assert prefix == "poster_"
        assert suffix == ".jpg"
        created_fd = os.open(tmp_poster, os.O_CREAT | os.O_RDWR)
        return created_fd, str(tmp_poster)

    def fake_run(command, **kwargs):
        if command[0] == "ffmpeg":
            tmp_poster.write_bytes(b"poster-bytes")
        return None

    mocker.patch("cast.models.video.tempfile.mkstemp", side_effect=fake_mkstemp)
    mocker.patch("cast.models.video.Video._get_video_dimensions", return_value=(1, 1))
    mocker.patch("cast.models.video.subprocess.run", side_effect=fake_run)
    poster_save = mocker.patch("cast.models.video.Video.poster.field.attr_class.save")

    class Original:
        url = "https://example.com/video.mp4"

    video = Video()
    mocker.patch.object(video, "original", Original())
    video._create_poster()

    assert created_fd is not None
    with pytest.raises(OSError, match="Bad file descriptor"):
        os.fstat(created_fd)
    assert not tmp_poster.exists()
    assert poster_save.called


@pytest.mark.django_db
def test_video_create_poster_removes_temp_file_when_poster_save_fails(mocker, tmp_path):
    tmp_poster = tmp_path / "poster.jpg"
    created_fd, real_path = None, str(tmp_poster)

    def fake_mkstemp(prefix, suffix):
        nonlocal created_fd
        assert prefix == "poster_"
        assert suffix == ".jpg"
        created_fd = os.open(real_path, os.O_CREAT | os.O_RDWR)
        return created_fd, real_path

    def fake_run(command, **kwargs):
        if command[0] == "ffmpeg":
            tmp_poster.write_bytes(b"poster-bytes")
        return None

    mocker.patch("cast.models.video.tempfile.mkstemp", side_effect=fake_mkstemp)
    mocker.patch("cast.models.video.Video._get_video_dimensions", return_value=(1, 1))
    mocker.patch("cast.models.video.subprocess.run", side_effect=fake_run)
    mocker.patch("cast.models.video.Video.poster.field.attr_class.save", side_effect=RuntimeError("save failed"))

    class Original:
        url = "https://example.com/video.mp4"

    video = Video()
    mocker.patch.object(video, "original", Original())
    with pytest.raises(RuntimeError, match="save failed"):
        video._create_poster()

    assert created_fd is not None
    with pytest.raises(OSError, match="Bad file descriptor"):
        os.fstat(created_fd)
    assert not tmp_poster.exists()


@pytest.mark.django_db
def test_video_create_poster_handles_missing_temp_file_on_success(mocker, tmp_path):
    tmp_poster = tmp_path / "poster.jpg"
    created_fd: int | None = None

    def fake_mkstemp(prefix, suffix):
        nonlocal created_fd
        assert prefix == "poster_"
        assert suffix == ".jpg"
        created_fd = os.open(tmp_poster, os.O_CREAT | os.O_RDWR)
        return created_fd, str(tmp_poster)

    def fake_run(command, **kwargs):
        if command[0] == "ffmpeg" and tmp_poster.exists():
            tmp_poster.write_bytes(b"poster-bytes")
        return None

    def fake_save(_name, content, save=False):
        del save
        os.unlink(content.file.name)

    mocker.patch("cast.models.video.tempfile.mkstemp", side_effect=fake_mkstemp)
    mocker.patch("cast.models.video.Video._get_video_dimensions", return_value=(1, 1))
    mocker.patch("cast.models.video.subprocess.run", side_effect=fake_run)
    mocker.patch("cast.models.video.Video.poster.field.attr_class.save", side_effect=fake_save)

    class Original:
        url = "https://example.com/video.mp4"

    video = Video()
    mocker.patch.object(video, "original", Original())
    video._create_poster()

    assert created_fd is not None
    with pytest.raises(OSError, match="Bad file descriptor"):
        os.fstat(created_fd)
    assert not tmp_poster.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("dimensions", [(None, None), (640, None), (None, 480)])
def test_video_create_poster_skips_ffmpeg_when_dimensions_missing(mocker, tmp_path, dimensions):
    tmp_poster = tmp_path / "poster.jpg"
    created_fd: int | None = None

    def fake_mkstemp(prefix, suffix):
        nonlocal created_fd
        assert prefix == "poster_"
        assert suffix == ".jpg"
        created_fd = os.open(tmp_poster, os.O_CREAT | os.O_RDWR)
        return created_fd, str(tmp_poster)

    mocker.patch("cast.models.video.tempfile.mkstemp", side_effect=fake_mkstemp)
    mocker.patch("cast.models.video.Video._get_video_dimensions", return_value=dimensions)
    run = mocker.patch("cast.models.video.subprocess.run")
    poster_save = mocker.patch("cast.models.video.Video.poster.field.attr_class.save")

    class Original:
        url = "https://example.com/video.mp4"

    video = Video()
    mocker.patch.object(video, "original", Original())

    video._create_poster()

    assert created_fd is not None
    with pytest.raises(OSError, match="Bad file descriptor"):
        os.fstat(created_fd)
    run.assert_not_called()
    poster_save.assert_not_called()
    assert not tmp_poster.exists()


@pytest.mark.django_db
def test_video_create_poster_handles_missing_dimensions_gracefully(mocker, tmp_path):
    tmp_poster = tmp_path / "poster.jpg"

    def fake_mkstemp(prefix, suffix):
        assert prefix == "poster_"
        assert suffix == ".jpg"
        return os.open(tmp_poster, os.O_CREAT | os.O_RDWR), str(tmp_poster)

    mocker.patch("cast.models.video.tempfile.mkstemp", side_effect=fake_mkstemp)
    mocker.patch("cast.models.video.Video._get_video_dimensions", return_value=(None, None))
    run = mocker.patch("cast.models.video.subprocess.run")
    poster_save = mocker.patch("cast.models.video.Video.poster.field.attr_class.save")

    class Original:
        url = "https://example.com/video.mp4"

    video = Video()
    mocker.patch.object(video, "original", Original())

    video.create_poster()

    run.assert_not_called()
    poster_save.assert_not_called()
    assert not tmp_poster.exists()
    assert not video.poster


@pytest.mark.django_db
def test_video_save_rolls_back_row_when_poster_generation_fails(monkeypatch, minimal_mp4, user):
    """Video.save enrichment must be all-or-nothing like Audio.save (architecture review H2)."""

    def boom(self):
        raise RuntimeError("poster generation failed")

    monkeypatch.setattr(Video, "create_poster", boom)
    video = Video(user=user, original=minimal_mp4)
    with pytest.raises(RuntimeError):
        save_video_with_derivations(video)
    assert Video.objects.count() == 0


@pytest.mark.django_db
def test_video_save_with_force_insert_does_not_attempt_second_insert(mocker, user, minimal_mp4):
    def fake_create_poster():
        video.poster.name = "cast_videos/poster/test.jpg"

    video = Video(user=user, title="force-insert video", original=minimal_mp4)
    create_poster = mocker.patch.object(video, "create_poster", side_effect=fake_create_poster)
    save_video_with_derivations(video, force_insert=True)

    assert video.pk is not None
    create_poster.assert_called_once()
    video.refresh_from_db()
    assert video.poster.name == "cast_videos/poster/test.jpg"


@pytest.mark.django_db
def test_video_save_propagates_using_on_poster_update(mocker, user):
    save_calls = []

    def fake_save(_self, *args, **kwargs):
        save_calls.append(kwargs.copy())
        return None

    mocker.patch("model_utils.models.TimeStampedModel.save", autospec=True, side_effect=fake_save)
    video = Video(user=user, title="poster update")

    def fake_create_poster():
        video.poster.name = "poster.jpg"

    mocker.patch.object(video, "create_poster", side_effect=fake_create_poster)

    save_video_with_derivations(video, using="default")

    assert save_calls[0]["using"] == "default"
    assert save_calls[1]["using"] == "default"
    assert save_calls[1]["update_fields"] == ["poster"]
