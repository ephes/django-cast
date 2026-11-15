"""Poster publication, diagnostic privacy and output allocation boundaries."""

import json
import logging
import subprocess
from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.core.management import CommandError, call_command
from PIL import Image

from cast.models import Video, get_video_dimensions


@pytest.mark.django_db
@pytest.mark.parametrize("edit", ["title", "original", "poster", "poster_seconds", "database-failure"])
def test_recalc_compares_current_generation_and_preserves_edits(video, tmp_path, monkeypatch, mocker, edit):
    storage = FileSystemStorage(location=tmp_path)
    monkeypatch.setattr(Video._meta.get_field("poster"), "storage", storage)
    video.poster = ""
    video.save(poster=False)
    storage.save("editor.jpg", ContentFile(b"editor"))
    created = []

    def create(instance):
        updates = {
            edit: {"title": "Editor title", "original": "new.mp4", "poster": "editor.jpg", "poster_seconds": 8}.get(
                edit
            )
        }
        if edit != "database-failure":
            Video.objects.filter(pk=instance.pk).update(**updates)
        instance.poster.save("attempt.jpg", ContentFile(b"attempt"), save=False)
        created.append(instance.poster.name)
        if edit == "database-failure":
            mocker.patch("django.db.models.query.QuerySet.update", side_effect=RuntimeError("synthetic DB failure"))

    monkeypatch.setattr(Video, "_create_poster", create)
    output, errors = StringIO(), StringIO()
    if edit == "title":
        call_command("recalc_video_posters", stdout=output, stderr=errors)
    else:
        with pytest.raises(CommandError):
            call_command("recalc_video_posters", stdout=output, stderr=errors)
    video.refresh_from_db()
    assert storage.exists("editor.jpg")
    assert storage.exists(created[0]) == (edit == "title")
    if edit == "title":
        assert video.title == "Editor title" and video.poster.name == created[0]
    elif edit == "poster":
        assert video.poster.name == "editor.jpg"
    else:
        assert not video.poster


@pytest.mark.django_db
@pytest.mark.parametrize("phase", ["probe", "extract", "success"])
def test_signed_urls_and_probe_errors_do_not_escape_diagnostics(mocker, caplog, capsys, phase):
    sentinel = "SYNTHETIC_CAPABILITY_SECRET"
    url = f"https://user:{sentinel}@media.example/movie.mp4?sig={sentinel}#{sentinel}"
    video = Video(pk=123)
    mocker.patch.object(video, "original", SimpleNamespace(url=url))
    commands = []

    def probe(command, **kwargs):
        commands.append((command, kwargs))
        if (phase == "probe" and command[0] == "ffprobe") or (phase == "extract" and command[0] == "ffmpeg"):
            raise subprocess.CalledProcessError(1, command, stderr=sentinel)
        if command[0] == "ffprobe":
            return SimpleNamespace(stdout=b'{"streams":[{"codec_type":"video","width":2,"height":2}]}')
        Image.new("RGB", (2, 2)).save(command[-1], "JPEG")
        return SimpleNamespace(stdout=b"")

    mocker.patch("cast.models.video.run_media_probe", side_effect=probe)
    mocker.patch.object(type(video.poster), "save")
    with caplog.at_level(logging.INFO, logger="cast.models.video"):
        video.create_poster()
    assert sentinel not in caplog.text + capsys.readouterr().err
    assert "123" in caplog.text and "poster" in caplog.text
    assert all(url in cmd for cmd, _ in commands)
    if len(commands) == 2:
        assert commands[-1][1]["stderr"] == subprocess.PIPE


@pytest.mark.django_db
@pytest.mark.parametrize(
    "width,height,ratio",
    [
        (1000000, 1, "1:1"),
        (1, 1, "1e1000000000:1"),
        (8192, 8192, "1:1"),
        (1, 1, "1" + "0" * 300 + ":1"),
    ],
)
def test_oversized_metadata_never_launches_extraction(mocker, width, height, ratio):
    stream = {"codec_type": "video", "width": width, "height": height, "sample_aspect_ratio": ratio}
    assert get_video_dimensions([json.dumps({"streams": [stream]})]) == (None, None)
    video = Video(pk=123, original="synthetic.mp4")
    mocker.patch.object(video, "original", SimpleNamespace(url="https://media.example/synthetic.mp4"))
    probe = mocker.patch(
        "cast.models.video.run_media_probe",
        return_value=SimpleNamespace(stdout=json.dumps({"streams": [stream]}).encode()),
    )
    video.create_poster()
    assert probe.call_count == 1
    assert not video.poster


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("edit", ["title", "original", "poster"])
def test_recalc_editor_interleaving_across_connections(user, tmp_path, monkeypatch, edit):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from django.db import close_old_connections
    from wagtail.models import Collection

    collection = Collection.get_first_root_node() or Collection.add_root(instance=Collection(name="Root"))
    video = Video.objects.create(user=user, collection=collection, title="Synthetic", original="synthetic.mp4")
    storage = FileSystemStorage(location=tmp_path)
    monkeypatch.setattr(Video._meta.get_field("poster"), "storage", storage)
    video.poster = ""
    video.save(poster=False)
    ready, release = threading.Event(), threading.Event()
    names = []

    def create(instance):
        ready.set()
        assert release.wait(10)
        instance.poster.save("attempt.jpg", ContentFile(b"attempt"), save=False)
        names.append(instance.poster.name)

    monkeypatch.setattr(Video, "_create_poster", create)

    def recalc():
        close_old_connections()
        try:
            call_command("recalc_video_posters", stdout=StringIO(), stderr=StringIO())
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(recalc)
        try:
            assert ready.wait(10)
            Video.objects.filter(pk=video.pk).update(**{edit: "editor-change"})
        finally:
            release.set()
        if edit == "title":
            pending.result(timeout=10)
        else:
            with pytest.raises(CommandError):
                pending.result(timeout=10)
    video.refresh_from_db()
    assert getattr(video, edit) == "editor-change"
    assert storage.exists(names[0]) == (edit == "title")


@pytest.mark.django_db
def test_failed_poster_attempt_does_not_delete_a_referenced_object(video, tmp_path, mocker, monkeypatch):
    storage = FileSystemStorage(location=tmp_path)
    monkeypatch.setattr(Video._meta.get_field("poster"), "storage", storage)
    video.poster = ""
    video.save(poster=False)

    def create(instance):
        instance.poster.save("attempt.jpg", ContentFile(b"attempt"), save=False)
        Video.objects.filter(pk=video.pk).update(poster=instance.poster.name)
        raise RuntimeError("failure after another publisher referenced the object")

    mocker.patch.object(Video, "_create_poster", create)
    with pytest.raises(RuntimeError):
        video.publish_missing_poster()
    assert storage.exists(video.poster.name)


@pytest.mark.django_db
def test_probe_timeout_has_a_safe_category(mocker, caplog):
    video = Video(pk=42)
    mocker.patch.object(Video, "_create_poster", side_effect=subprocess.TimeoutExpired("PRIVATE-URL", 30))
    with caplog.at_level(logging.INFO, logger="cast.models.video"):
        video.create_poster()
    assert "result=timeout" in caplog.text and "PRIVATE-URL" not in caplog.text


@pytest.mark.parametrize("rotation,expected", [(0, (8192, 2048)), (90, (2048, 8192))])
def test_exact_poster_output_budget_preserves_geometry(rotation, expected):
    stream = {
        "codec_type": "video",
        "width": 16384,
        "height": 2048,
        "sample_aspect_ratio": "1:2",
        "tags": {"rotate": rotation},
    }
    assert get_video_dimensions([json.dumps({"streams": [stream]})]) == expected
