from datetime import timedelta

import pytest


class TestImageModel:
    @pytest.mark.django_db
    def test_get_all_image_paths(self, image):
        all_paths = list(image.get_all_paths())
        assert len(all_paths) == len(image.IMAGE_SIZES) + 1

    @pytest.mark.django_db
    def test_get_srset(self, image):
        assert len(image.srcset.split(",")) == len(image.IMAGE_SIZES) + 1

    @pytest.mark.django_db
    def test_thumbnail_src(self, image):
        assert image.thumbnail_src.endswith("jpg")

    @pytest.mark.django_db
    def test_full_src(self, image):
        assert image.full_src.endswith("jpg")


class TestVideoModel:
    @pytest.mark.django_db
    def test_get_all_video_paths(self, video):
        all_paths = list(video.get_all_paths())
        assert len(all_paths) == 1

    @pytest.mark.django_db
    def test_get_all_video_paths_with_poster(self, video_with_poster):
        all_paths = list(video_with_poster.get_all_paths())
        assert len(all_paths) == 3

    @pytest.mark.django_db
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


class TestAudioModel:
    @pytest.mark.django_db
    def test_get_file_formats(self, audio):
        assert audio.file_formats == "m4a"

    @pytest.mark.django_db
    def test_get_file_names(self, audio):
        assert "test" in audio.get_audio_file_names()

    @pytest.mark.django_db
    def test_get_name(self, audio):
        assert audio.name == "test"

    @pytest.mark.django_db
    def test_get_name_with_title(self, audio):
        title = "foobar"
        audio.title = title
        assert audio.name == title

    @pytest.mark.django_db
    def test_audio_str(self, audio):
        assert "1 - test" == str(audio)

    @pytest.mark.django_db
    def test_audio_get_all_paths(self, audio):
        assert "cast_audio/test.m4a" in audio.get_all_paths()

    @pytest.mark.django_db
    def test_audio_duration(self, audio):
        duration = audio._get_audio_duration(audio.m4a.path)
        assert duration == timedelta(microseconds=700000)

    @pytest.mark.django_db
    def test_audio_create_duration(self, audio):
        duration = "00:01:01.00"
        audio._get_audio_duration = lambda x: duration
        audio.create_duration()
        assert audio.duration == duration

    @pytest.mark.django_db
    def test_audio_podlove_url(self, audio):
        assert audio.podlove_url == "/api/audios/podlove/1"


class TestFileModel:
    @pytest.mark.django_db
    def test_get_all_file_paths(self, file_instance):
        all_paths = list(file_instance.get_all_paths())
        assert len(all_paths) == 1


class TestBlogModel:
    @pytest.mark.django_db
    def test_blog_str(self, blog):
        assert blog.title == str(blog)

    @pytest.mark.django_db
    def test_blog_author_null(self, blog):
        blog.author = None
        assert blog.author_name == blog.user.get_full_name()

    @pytest.mark.django_db
    def test_blog_author_not_null(self, blog):
        blog.author = "Foobar"
        assert blog.author_name == blog.author


class TestPostModel:
    @pytest.mark.django_db
    def test_post_slug(self, post):
        assert post.get_slug() == "test-entry"

    @pytest.mark.django_db
    def test_post_has_audio(self, post):
        assert post.has_audio is False

    @pytest.mark.django_db
    def test_post_has_audio_true(self, post, audio):
        post.podcast_audio = audio
        assert post.has_audio is True

    @pytest.mark.django_db
    def test_post_comments_enabled(self, post, comments_enabled):
        post.comments_enabled = True
        post.blog.comments_enabled = True
        assert post.comments_are_enabled

    @pytest.mark.django_db
    def test_post_comments_disabled_settings(self, post, comments_not_enabled):
        post.comments_enabled = True
        post.blog.comments_enabled = True
        assert not post.comments_are_enabled

    @pytest.mark.django_db
    def test_post_comments_disabled_blog(self, post, comments_enabled):
        post.comments_enabled = True
        post.blog.comments_enabled = False
        assert not post.comments_are_enabled

    @pytest.mark.django_db
    def test_post_comments_disabled_post(self, post, comments_enabled):
        post.comments_enabled = False
        post.blog.comments_enabled = True
        assert not post.comments_are_enabled


class TestChapterMarkModel:
    @pytest.mark.django_db
    def test_chaptermark_original_line(self, chaptermarks):
        chaptermark = chaptermarks[0]
        assert chaptermark.original_line == "00:01:01.234 introduction  "

    @pytest.mark.django_db
    def test_chaptermark_original_line_link(self, chaptermarks):
        link = "http://foobar.com"
        chaptermark = chaptermarks[0]
        chaptermark.link = link
        assert chaptermark.original_line == f"00:01:01.234 introduction {link} "

    @pytest.mark.django_db
    def test_chaptermark_original_line_image(self, chaptermarks):
        image = "http://foobar.com/blub.jpg"
        chaptermark = chaptermarks[0]
        chaptermark.image = image
        assert chaptermark.original_line == f"00:01:01.234 introduction  {image}"
