from datetime import timedelta

import pytest

from cast.models.audio import Audio, ChapterMark, sync_chapter_marks


class TestAudioModel:
    pytestmark = pytest.mark.django_db

    def test_get_file_formats(self, audio):
        assert audio.file_formats == "m4a"

    def test_get_file_names(self, audio):
        assert "test" in audio.get_audio_file_names()

    def test_get_name(self, audio):
        audio.title = None  # make sure name is provided by file
        assert audio.name == "test"

    def test_get_name_with_title(self, audio):
        title = "foobar"
        audio.title = title
        assert audio.name == title

    def test_audio_str(self, audio):
        audio.title = None  # make sure name is provided by file
        assert "1 - test" == str(audio)

    def test_audio_get_all_paths(self, audio):
        assert "cast_audio/test.m4a" in audio.get_all_paths()

    def test_audio_duration(self, audio):
        duration = audio._get_audio_duration(audio.m4a.path)
        assert duration in (timedelta(microseconds=746667), timedelta(microseconds=700000))

    def test_audio_duration_no_match(self, mocker):
        mocker.patch("cast.models.audio.subprocess.check_output", return_value=b"foobar")
        with pytest.raises(ValueError):
            Audio._get_audio_duration("https://example.com/test.m4a")

    def test_audio_create_duration(self, audio):
        duration = "00:01:01.00"
        audio._get_audio_duration = lambda x: duration
        audio.create_duration()
        assert audio.duration == duration

    def test_audio_create_duration_no_duration(self, audio, mocker):
        class Field:
            url = "https://example.com/to.mp3"
            path = "/tmp/to.mp3"

        field = Field()
        get_audio_duration = mocker.patch("cast.models.audio.Audio._get_audio_duration", return_value="duration")
        mocker.patch("cast.models.audio.Audio.uploaded_audio_files", [("mp3", field)])
        audio.create_duration()
        get_audio_duration.assert_called_once_with(field.url)

    def test_audio_create_duration_no_file_field(self, audio, mocker):
        class Field:  # not a FileField
            foo = "bar"

        field = Field()
        get_audio_duration = mocker.patch("cast.models.audio.Audio._get_audio_duration", return_value="duration")
        mocker.patch("cast.models.audio.Audio.uploaded_audio_files", [("mp3", field)])
        audio.create_duration()
        assert get_audio_duration.call_count == 0

    def test_audio_audio_without_file_fields(self, audio, mocker):
        class Field:  # not a FileField
            foo = "bar"

        field = Field()
        mocker.patch("cast.models.audio.Audio.uploaded_audio_files", [("mp3", field)])
        assert audio.audio == []

    def test_audio_get_chaptermark_data_from_file_https_not_in_url(self, audio, mocker):
        class RunReturn:
            stdout = '{"foo": "bar"}'

        class Field:
            url = "https://example.com/to.mp3"
            path = "/tmp/to.mp3"

        field = Field()
        mocker.patch("cast.models.audio.getattr", return_value=field)
        run = mocker.patch("cast.models.audio.subprocess.run", return_value=RunReturn())
        mocker.patch("cast.models.audio.Audio.clean_ffprobe_chaptermarks")
        _ = audio.get_chaptermark_data_from_file("mp3")
        assert field.url == run.call_args[0][0][2]

    def test_audio_podlove_url(self, audio):
        assert audio.podlove_url == "/cast/api/audios/podlove/1"

    def test_get_episode_url_from_audio(self, episode):
        audio = episode.podcast_audio

        # happy path - audio has episode and episode_id is set
        audio.set_episode_id(episode.pk)
        assert "http" in audio.episode_url

        # happy path - audio is only used by one episode
        del audio._episode_id
        assert "http" in audio.episode_url

        # sad path - audio is not used by any episode
        episode.unpublish()
        episode.podcast_audio = None
        episode.save()
        assert audio.episode_url is None

    def test_get_episode_url_from_audio_with_multiple_episodes(self, episode, podcast_episode_with_same_audio):
        audio = episode.podcast_audio

        # sad path - audio is used by multiple episodes
        assert audio.episode_url is None

        # happy path - audio is used by multiple episodes but episode_id is set
        audio.set_episode_id(episode.pk)
        assert audio.episode_url == episode.full_url

        audio.set_episode_id(podcast_episode_with_same_audio.pk)
        assert audio.episode_url == podcast_episode_with_same_audio.full_url

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

    def test_chapters_as_text_chaptermarks_not_empty(self, audio, mocker):
        class Mark:
            original_line = "original line"

        mark = Mark()

        class ChapterMarks:
            @staticmethod
            def order_by(_order):
                return [mark]

        mocker.patch("cast.models.audio.Audio.chaptermarks", ChapterMarks())
        assert mark.original_line in audio.chapters_as_text

    def test_write_audio_file_size_to_cache(self, audio):
        expected_size = audio.m4a.size
        audio.size_to_metadata()
        assert audio.data["size"]["m4a"] == expected_size

    def test_read_audio_file_size_from_cache(self, audio):
        # when size is not in cache, it should be read from file
        expected_file_size = audio.m4a.size
        audio.data = {}
        assert audio.get_file_size("m4a") == expected_file_size

        # when size is in cache, it should be read from cache
        expected_cache_size = 123
        audio.data = {"size": {"m4a": expected_cache_size}}
        assert audio.get_file_size("m4a") == expected_cache_size

        # when file field is null, return 0
        audio.mp3 = None
        assert audio.get_file_size("mp3") == 0

    def test_save_without_cache_file_sizes(self, audio, mocker):
        mocker.patch("cast.models.audio.TimeStampedModel.save")
        audio.data = expected_data = {}
        audio.save(generate_duration=False, cache_file_sizes=False)
        assert audio.data == expected_data


class TestChapterMarkModel:
    pytestmark = pytest.mark.django_db

    def test_chaptermark_original_line(self, chaptermarks):
        chaptermark = chaptermarks[0]
        assert chaptermark.original_line == "00:01:01.234 introduction  "

    def test_chaptermark_original_line_link(self, chaptermarks):
        link = "https://foobar.com"
        chaptermark = chaptermarks[0]
        chaptermark.link = link
        assert chaptermark.original_line == f"00:01:01.234 introduction {link} "

    def test_chaptermark_original_line_image(self, chaptermarks):
        image = "https://foobar.com/blub.jpg"
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
