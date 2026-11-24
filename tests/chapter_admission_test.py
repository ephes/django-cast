"""Elapsed chapter admission and bounded linear text parsing."""

import json
from datetime import time
from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError

from cast.forms import AudioForm, ChapterMarksField, FFProbeChapterMarkForm, FFProbeStartField
from cast.models import ChapterMark


@pytest.mark.parametrize(
    "value", [-1, "-0.01", 86400, "nan", "inf", "1e100", "1e999", "86399.9999999", 10**400, object()]
)
def test_ffprobe_offsets_outside_time_domain(value):
    with pytest.raises(ValidationError):
        FFProbeStartField().clean(value)
    assert not FFProbeChapterMarkForm({"start": value, "title": "Synthetic"}).is_valid()


@pytest.mark.parametrize(
    "value, expected", [("0", time()), ("155.343", time(0, 2, 35, 343000)), ("86399.999999", time(23, 59, 59, 999999))]
)
def test_ffprobe_offset_precision(value, expected):
    assert FFProbeStartField().clean(value) == expected


@pytest.mark.django_db
@pytest.mark.parametrize("value", ["-1", "86400", "1e100"])
def test_rejected_extracted_offsets_preserve_chapters(audio, m4a_audio, mocker, value, caplog):
    old = ChapterMark.objects.create(audio=audio, start=time(), title="Keep")
    form = AudioForm({}, files={"m4a": m4a_audio}, instance=audio)
    assert form.is_valid()
    audio.m4a = "cast_audio/previous.m4a"
    mocker.patch.object(
        audio,
        "get_chaptermark_data_from_file",
        return_value=[{"start": "1.5", "title": "Partial"}, {"start": value, "title": "Bad"}],
    )
    form.save_chaptermarks(audio)
    assert "Skipping audio chapter extraction after invalid chapter data" in caplog.text
    assert form.cleaned_data["chaptermarks"] == []
    assert list(audio.chaptermarks.values_list("pk", "title")) == [(old.pk, "Keep")]


@pytest.mark.parametrize("size", [100, 500, 1000])
def test_chapter_membership_work_is_linear(monkeypatch, size):
    class Start:
        comparisons = 0

        def __init__(self, value):
            self.value = value

        def __hash__(self):
            return self.value

        def __eq__(self, other):
            Start.comparisons += 1
            return self.value == other.value

    monkeypatch.setattr("cast.forms.parse_chaptermark_line", lambda line: SimpleNamespace(start=Start(int(line))))
    marks = ChapterMarksField().to_python("\n".join(map(str, range(size))))
    assert [mark.start.value for mark in marks] == list(range(size))
    assert Start.comparisons <= size * 2


@pytest.mark.parametrize("value", ["00:00:00 X\n" * 1001, "x" * 262145])
def test_chapter_work_limit_precedes_forms(value, mocker):
    parse = mocker.patch("cast.forms.parse_chaptermark_line")
    with pytest.raises(ValidationError, match="Chapter input exceeds"):
        ChapterMarksField().to_python(value)
    parse.assert_not_called()


@pytest.mark.django_db
def test_over_budget_audio_form_keeps_chapters(audio):
    old = ChapterMark.objects.create(audio=audio, start=time(), title="Keep")
    form = AudioForm({"chaptermarks": "00:00:00 X\n" * 1001}, instance=audio)
    assert not form.is_valid()
    assert "Chapter input exceeds" in str(form.errors["chaptermarks"])
    assert audio.chaptermarks.get().pk == old.pk


@pytest.mark.django_db
def test_embedded_titles_are_normalized_before_chapter_sync(audio, m4a_audio, mocker):
    ChapterMark.objects.create(audio=audio, start=time(), title="Old")
    form = AudioForm({}, files={"m4a": m4a_audio}, instance=audio)
    assert form.is_valid()
    audio.m4a = "cast_audio/previous.m4a"
    chapters = [
        {"start_time": "1", "tags": {"title": " \t "}},
        {"start_time": "2", "tags": {"title": "  First  "}},
        {"start_time": "3", "tags": {"title": "Second  chapter"}},
    ]
    mocker.patch(
        "cast.models.audio.run_media_probe", return_value=SimpleNamespace(stdout=json.dumps({"chapters": chapters}))
    )
    form.save_chaptermarks(audio)
    assert list(audio.chaptermarks.order_by("start").values_list("start", "title")) == [
        (time(0, 0, 2), "First"),
        (time(0, 0, 3), "Second  chapter"),
    ]
