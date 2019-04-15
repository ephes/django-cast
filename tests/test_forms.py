import pytest

from cast.forms import ChapterMarkForm


class TestChapterMarkForm:
    @pytest.mark.django_db
    def test_add_chapter_mark_form(self, audio):
        row = {"audio": audio.pk, "start": "01:01:01.123", "title": "foo bar baz"}
        form = ChapterMarkForm(row)
        assert form.is_valid()

    @pytest.mark.django_db
    def test_add_chapter_mark_form_invalid_url(self, audio):
        row = {
            "audio": audio.pk,
            "start": "01:01:01.123",
            "title": "foo bar baz",
            "link": "foobar",
        }
        form = ChapterMarkForm(row)
        assert not form.is_valid()
