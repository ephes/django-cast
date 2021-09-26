from datetime import timedelta

import pytest

from cast.models import Audio, ChapterMark, sync_chapter_marks


class TestVideoModel:
    @pytest.mark.django_db
    def test_get_all_video_paths(self, video):
        all_paths = list(video.get_all_paths())
        assert len(all_paths) == 1

    @pytest.mark.django_db
    def test_get_all_video_paths_with_poster(self, video_with_poster):
        all_paths = list(video_with_poster.get_all_paths())
        assert len(all_paths) == 2

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
        audio.title = None  # make sure name is provided by file
        assert audio.name == "test"

    @pytest.mark.django_db
    def test_get_name_with_title(self, audio):
        title = "foobar"
        audio.title = title
        assert audio.name == title

    @pytest.mark.django_db
    def test_audio_str(self, audio):
        audio.title = None  # make sure name is provided by file
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
        assert audio.podlove_url == "/cast/api/audios/podlove/1"

    @pytest.mark.django_db
    def test_audio_get_chaptermark_data_from_file_empty_on_value_error(self, audio):
        assert audio.get_chaptermark_data_from_file("mp3") == []

    def test_audio_test_clean_ffprobe_chaptermarks(self):
        ffprobe_chaptermarks = {
            "chapters": [
                {
                    "id": 0,
                    "time_base": "1/1000",
                    "start": 0,
                    "start_time": "0.000000",
                    "end": 155343,
                    "end_time": "155.343000",
                    # chapter marks with empty title should be filtered
                    "tags": {"title": ""},
                },
                {
                    "id": 1,
                    "time_base": "1/1000",
                    "start": 155343,
                    "start_time": "155.343000",
                    "end": 617117,
                    "end_time": "617.117000",
                    "tags": {"title": "News aus der Szene"},
                },
                {
                    "id": 2,
                    "time_base": "1/1000",
                    "start": 617117,
                    "start_time": "617.117000",
                    "end": 1266062,
                    "end_time": "1266.062000",
                    "tags": {"title": "Django Async"},
                },
            ]
        }
        cleaned_chaptermarks = Audio.clean_ffprobe_chaptermarks(ffprobe_chaptermarks)
        assert len(cleaned_chaptermarks) == 2
        assert cleaned_chaptermarks == [
            {"start": "155.343000", "title": "News aus der Szene"},
            {"start": "617.117000", "title": "Django Async"},
        ]


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
        assert blog.author_name == blog.owner.get_full_name()

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
    pytestmark = pytest.mark.django_db

    def test_chaptermark_original_line(self, chaptermarks):
        chaptermark = chaptermarks[0]
        assert chaptermark.original_line == "00:01:01.234 introduction  "

    def test_chaptermark_original_line_link(self, chaptermarks):
        link = "http://foobar.com"
        chaptermark = chaptermarks[0]
        chaptermark.link = link
        assert chaptermark.original_line == f"00:01:01.234 introduction {link} "

    def test_chaptermark_original_line_image(self, chaptermarks):
        image = "http://foobar.com/blub.jpg"
        chaptermark = chaptermarks[0]
        chaptermark.image = image
        assert chaptermark.original_line == f"00:01:01.234 introduction  {image}"


def start_strings_to_chaptermarks(audio, start_strings):
    chaptermarks = []
    for start_string in start_strings:
        cm = ChapterMark(audio=audio, start=start_string, title="foobar")
        cm.full_clean()  # convert string to datetime.time
        chaptermarks.append(cm)
    return chaptermarks


def chaptermarks_are_equal(actual, expected):
    if len(actual) != len(expected):
        return False
    attributes_to_compare = ["start", "title"]
    for a, b in zip(actual, expected):
        for attr in attributes_to_compare:
            if getattr(a, attr) != getattr(b, attr):
                return False
    return True


@pytest.mark.parametrize(
    "from_database, from_cms, expected_to_add, expected_to_update, expected_to_remove",
    [
        # from_database, from_cms, expected_to_add, expected_to_update, expected_to_remove
        ([], [], [], [], []),
        ([], ["0:0"], ["0:0"], [], []),  # add chaptermark
        (["0:0"], ["0:0"], [], [], []),  # update chaptermark -> empty because equal
        (["0:0"], [], [], [], ["0:0"]),  # remove chaptermark
        # add, update and remove together
        (["0:0", "0:2"], ["0:0", "0:1"], ["0:1"], [], ["0:2"]),
    ],
)
@pytest.mark.django_db
def test_sync_chapter_marks(from_database, from_cms, expected_to_add, expected_to_update, expected_to_remove, audio):
    args = []
    for start_string_list in [from_database, from_cms, expected_to_add, expected_to_update, expected_to_remove]:
        args.append(start_strings_to_chaptermarks(audio, start_string_list))
    from_database, from_cms, expected_to_add, expected_to_update, expected_to_remove = args
    actual_to_add, actual_to_update, actual_to_remove = sync_chapter_marks(from_database, from_cms)
    for actual, expected in zip(
        [actual_to_add, actual_to_update, actual_to_remove], [expected_to_add, expected_to_update, expected_to_remove]
    ):
        assert chaptermarks_are_equal(actual, expected)


@pytest.mark.django_db
def test_sync_chapter_marks_update_changed_chaptermarks(audio):
    cm1 = ChapterMark(audio=audio, start="0:0", title="foobar")
    cm1.full_clean()
    cm2 = ChapterMark(audio=audio, start="0:0", title="changed")
    cm2.full_clean()
    actual_to_add, actual_to_update, actual_to_remove = sync_chapter_marks([cm1], [cm2])
    assert len(actual_to_update) == 1
