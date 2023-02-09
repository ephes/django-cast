from unittest.mock import MagicMock

import pytest

from cast.forms import AudioForm, ChapterMarkForm, get_video_form
from cast.models import Audio, ChapterMark


class TestChapterMarkForm:
    pytestmark = pytest.mark.django_db

    def test_add_chapter_mark_form(self, audio):
        row = {"audio": audio.pk, "start": "01:01:01.123", "title": "foo bar baz"}
        form = ChapterMarkForm(row)
        assert form.is_valid()

    def test_add_chapter_mark_form_invalid_url(self, audio):
        row = {
            "audio": audio.pk,
            "start": "01:01:01.123",
            "title": "foo bar baz",
            "link": "foobar",
        }
        form = ChapterMarkForm(row)
        assert not form.is_valid()


class TestAudioForm:
    pytestmark = pytest.mark.django_db

    def test_chaptermarks_not_set(self):
        form = AudioForm({})
        assert form.is_valid()
        assert form.cleaned_data["chaptermarks"] == []

    def test_chaptermarks_empty(self):
        form = AudioForm({"chaptermarks": ""})
        assert form.is_valid()
        assert form.cleaned_data["chaptermarks"] == []

    def test_chaptermarks_invalid_line(self):
        broken_line = "00:12:24.409Dokumentation"
        chaptermarks = "\n".join(
            [
                "00:00:28.433 News aus der Szene",
                "00:02:40.964 Packaging",
                broken_line,
            ]
        )
        form = AudioForm({"chaptermarks": chaptermarks})
        assert form.is_valid() is False
        assert broken_line in form.errors["chaptermarks"][0]

    def test_chaptermarks_invalid_start(self):
        invalid_start = "invalid Dokumentation"
        chaptermarks = "\n".join(
            [
                "00:00:28.433 News aus der Szene",
                "00:02:40.964 Packaging",
                invalid_start,
            ]
        )
        form = AudioForm({"chaptermarks": chaptermarks})
        assert form.is_valid() is False
        assert invalid_start in form.errors["chaptermarks"][0]

    def test_chaptermarks_happy_path(self, user):
        expected_first_title = "News aus der Szene"
        chaptermarks = "\n".join(
            [
                f"00:00:28.433 {expected_first_title}",
                "00:02:40.964 Packaging",
                "00:12:24.409 Dokumentation",
            ]
        )

        # make sure audio form is valid
        audio = Audio(user=user)
        form = AudioForm({"chaptermarks": chaptermarks}, instance=audio)
        assert form.is_valid()
        cleaned_chaptermarks = form.cleaned_data["chaptermarks"]
        assert cleaned_chaptermarks[0].title == expected_first_title

        # make sure chaptermarks are not saved on commit=False
        audio = form.save(commit=False)
        assert ChapterMark.objects.count() == 0

        # make sure chaptermarks are saved in db on form.save()
        audio = form.save(commit=True)
        assert audio.chaptermarks.count() == 3
        assert audio.chaptermarks.order_by("start").first().title == expected_first_title

    def test_old_chaptermarks_are_removed(self, audio):
        ChapterMark.objects.create(audio=audio, start="00:00:28.433", title="old chaptermark")
        assert audio.chaptermarks.count() == 1

        form = AudioForm({}, instance=audio)
        assert form.is_valid()

        # assert old chaptermark was removed
        audio = form.save(commit=True)
        assert audio.chaptermarks.count() == 0

    def test_chaptermarks_from_file(self, audio, m4a_audio):
        expected_title = "News aus der Szene"
        chaptermarks_from_file = [
            {"start": "155.343000", "title": expected_title},
            {"start": "invalid", "title": expected_title},
        ]
        audio.get_chaptermark_data_from_file = MagicMock(return_value=chaptermarks_from_file)
        form = AudioForm({}, {"m4a": m4a_audio}, instance=audio)
        assert form.is_valid()
        assert form.save()

        # make sure chaptermark was saved with correct attributes
        saved_chaptermark = audio.chaptermarks.first()
        assert saved_chaptermark.title == expected_title
        assert str(saved_chaptermark.start) == "00:02:35.343000"  # == "155.343000"


def test_get_video_form_collection_not_added_if_in_admin_form_fields(mocker):
    mocker.patch("cast.forms.Video.admin_form_fields", ("title", "original", "poster", "tags", "collection"))
    video_form = get_video_form()
    assert "collection" in video_form._meta.fields
