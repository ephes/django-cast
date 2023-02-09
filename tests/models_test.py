import pytest
from django.http.request import QueryDict

from cast.models.pages import Episode, HomePage, Post
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

    def test_filterset_data_request_is_none(self, blog):
        blog.request = None

        # blog._filterset_data is None
        blog._filterset_data = None
        assert blog.filterset_data == QueryDict()

        # blog._filterset_data is not None
        blog._filterset_data = QueryDict()
        assert blog.filterset_data == QueryDict()

    def test_paginate_queryset_request_is_none(self, blog):
        blog.request = None
        context = blog.paginate_queryset({})
        assert context["page_obj"].number == 1

    def test_get_other_get_params_request_is_none(self, blog):
        blog.request = None
        assert blog.get_other_get_params() == ""

    def test_get_other_get_params_len_parameters_gt_0(self, blog):
        class Request:
            GET = QueryDict("foo=bar&bar=foo&page=3")

        request = Request()
        blog.request = request
        params = blog.get_other_get_params()
        assert params == "&foo=bar&bar=foo"


class TestPostModel:
    pytestmark = pytest.mark.django_db

    def test_post_slug(self, post):
        assert post.get_slug() == "test-entry"

    def test_post_has_audio(self, post):
        assert post.has_audio is False

    def test_episode_has_audio(self, episode):
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


def test_placeholder_request():
    from cast.models.pages import PlaceholderRequest

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
