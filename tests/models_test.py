import pytest
from django import forms
from django.http.request import QueryDict
from django.urls import reverse

from cast import appsettings
from cast.models.pages import (
    CustomEpisodeForm,
    Episode,
    HomePage,
    PlaceholderRequest,
    Post,
)
from cast.models.video import Video


class TestVideoModel:
    pytestmark = pytest.mark.django_db

    def test_get_all_video_paths(self, video):
        all_paths = list(video.get_all_paths())
        assert len(all_paths) == 1

    def test_get_all_video_paths_with_poster(self, video_with_poster):
        all_paths = list(video_with_poster.get_all_paths())
        assert len(all_paths) == 2

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

    def test_paginate_queryset_request_is_none(self, blog):
        context = blog.paginate_queryset({}, blog.get_filterset(QueryDict()).qs, QueryDict())
        assert context["page_obj"].number == 1

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

    def test_comment_post_url(self, blog):
        assert blog.comment_post_url == reverse("comments-post-comment-ajax")


class TestPostModel:
    pytestmark = pytest.mark.django_db

    def test_post_slug(self, post):
        assert post.get_slug() == "test-entry"

    def test_post_has_audio(self, post):
        assert post.has_audio is False

    def test_episode_has_audio(self, unpublished_episode_without_audio):
        episode = unpublished_episode_without_audio
        assert episode.has_audio is False

    def test_episode_has_audio_true(self, episode, audio):
        episode.podcast_audio = audio
        assert episode.has_audio is True

    def test_post_comments_enabled(self, post, comments_enabled):
        post.comments_enabled = True
        post.blog.comments_enabled = True
        assert post.comments_are_enabled

    def test_post_comments_disabled_settings(self, post, comments_not_enabled):
        post.comments_enabled = True
        post.blog.comments_enabled = True
        assert not post.comments_are_enabled

    def test_post_comments_disabled_blog(self, post, comments_enabled):
        post.comments_enabled = True
        post.blog.comments_enabled = False
        assert not post.comments_are_enabled

    def test_post_comments_disabled_post(self, post, comments_enabled):
        post.comments_enabled = False
        post.blog.comments_enabled = True
        assert not post.comments_are_enabled

    def test_post_media_lookup_value_error(self):
        assert Post().media_lookup == {}

    def test_post_has_audio_value_error(self):
        assert Post().has_audio is False

    def test_media_ids_from_body(self):
        class Block:
            block_type = "image"
            value = None

        class ContentBlock:
            value = (Block(),)

        block = ContentBlock()
        post = Post()
        assert post._media_ids_from_body([block]) == {}

    def test_get_description_escape(self, mocker):
        class Rendered:
            rendered_content = "<h1>foo</h1>"

        mocker.patch("cast.models.Post.serve", return_value=Rendered())
        post = Post()
        description = post.get_description(escape_html=True)
        assert "&lt" in description

    def test_get_description_newlines(self, mocker):
        class Rendered:
            rendered_content = "<h1>foo</h1>\n"

        mocker.patch("cast.models.Post.serve", return_value=Rendered())
        post = Post()
        description = post.get_description(remove_newlines=False)
        assert "\n" in description

    def test_overview_html(self, mocker):
        expected_html = "<h1>foo</h1>"
        mock = mocker.patch("cast.models.Post.get_description", return_value=expected_html)
        overview = Post().html_overview
        assert overview == expected_html
        assert mock.call_args[1]["render_detail"] is False
        assert mock.call_args[1]["escape_html"] is False
        assert mock.call_args[1]["remove_newlines"] is False

    def test_detail_html(self, mocker):
        expected_html = "<h1>foo</h1><p>bar</p>"
        mock = mocker.patch("cast.models.Post.get_description", return_value=expected_html)
        detail = Post().html_detail
        assert detail == expected_html
        assert mock.call_args[1]["render_detail"] is True
        assert mock.call_args[1]["escape_html"] is False
        assert mock.call_args[1]["remove_newlines"] is False

    @pytest.mark.parametrize(
        "local_template_name, expected_template",
        [
            (None, "cast/bootstrap4/post.html"),
            ("foobar.html", "cast/bootstrap4/foobar.html"),
        ],
    )
    def test_get_template_for_post(self, local_template_name, expected_template, mocker):
        class TemplateBaseDirectory:
            name = "bootstrap4"

        mocker.patch("cast.models.pages.TemplateBaseDirectory.for_request", return_value=TemplateBaseDirectory())
        post = Post()
        post._local_template_name = local_template_name

        assert post.get_template(PlaceholderRequest()) == expected_template

    @pytest.mark.parametrize(
        "is_public, is_removed, contained_in_list",
        [
            (True, False, True),  # public, not removed, in list
            (True, True, False),  # public, removed, not in list
            (False, True, False),  # not public, removed, not in list
            (False, False, False),  # not public, not removed, not in list
        ],
    )
    def test_get_comments(self, is_public, is_removed, contained_in_list, post, comment):
        comment.is_public = is_public
        comment.is_removed = is_removed
        comment.save()
        if contained_in_list:
            [json_comment] = post.comments
            assert json_comment["comment"] == comment.comment
        else:
            assert list(post.comments) == []

    def test_get_comments_is_public_and_is_removed_not_in_fields(self, mocker, post, comment):
        from django_comments import get_model as get_comment_model

        comment_model = get_comment_model()
        exclude = {"is_public", "is_removed"}
        fields_without_excluded = [field for field in comment_model._meta.fields if field.name not in exclude]
        mocker.patch("cast.models.pages.comment_model._meta.fields", fields_without_excluded)
        [json_comment] = post.comments
        assert json_comment["comment"] == comment.comment

    def test_page_type(self):
        post = Post()
        assert post.page_type == "cast.Post"

    def test_podlove_players(self, post_with_audio):
        post = post_with_audio
        [audio] = post.audios.all()
        assert post.podlove_players == [
            (f"#audio_{audio.pk}", audio.podlove_url),
        ]


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
    def test_get_template_for_episode(self, local_template_name, expected_template, mocker):
        class TemplateBaseDirectory:
            name = "bootstrap4"

        mocker.patch("cast.models.pages.TemplateBaseDirectory.for_request", return_value=TemplateBaseDirectory())
        episode = Episode()
        episode._local_template_name = local_template_name

        assert episode.get_template(PlaceholderRequest()) == expected_template

    def test_page_type(self):
        episode = Episode()
        assert episode.page_type == "cast.Episode"


@pytest.mark.django_db
def test_custom_episode_form():
    # arrange the custom episode form
    CustomEpisodeForm._meta.model = Episode
    CustomEpisodeForm._meta.fields = ("podcast_audio", "about_to_be_published")
    CustomEpisodeForm.formsets = {}

    # test the form with no data
    form = CustomEpisodeForm()
    assert not form.is_valid()

    # test the form with the "Save draft" button clicked (no audio file is ok)
    form = CustomEpisodeForm({"podcast_audio": None})
    assert form.is_valid()

    # test the form with the "Publish" button clicked (audio file is required)
    form = CustomEpisodeForm({"action-publish": "action-publish", "podcast_audio": None})
    form.fields["podcast_audio"] = forms.IntegerField(required=False)
    assert not form.is_valid()


def test_placeholder_request():
    request = PlaceholderRequest()
    assert "localhost" in request.get_host()
    assert request.get_port() == 80


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
def test_video_create_poster_video_url_without_http(mocker):
    mocker.patch("cast.models.video.tempfile.mkstemp", return_value=(1, "foo"))
    mocker.patch("cast.models.video.Video._get_video_dimensions", return_value=(1, 1))
    check_output = mocker.patch("cast.models.video.check_output", side_effect=ValueError())

    class Original:
        url = "https://example.com/video.mp4"

    video = Video()
    mocker.patch.object(video, "original", Original())
    with pytest.raises(ValueError):
        video._create_poster()
    command = check_output.call_args_list[0][0][0]
    assert "example" in command
