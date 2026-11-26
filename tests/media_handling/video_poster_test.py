"""Poster publication, diagnostic privacy and output allocation boundaries."""

import json
import logging
import subprocess
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.core.management import CommandError, call_command
from PIL import Image
from wagtail.models import Collection

from cast.management.commands import recalc_video_posters
from cast.models import Video, get_video_dimensions


@pytest.mark.django_db(databases={"default", "migration_other"})
def test_recalc_counts_and_repairs_videos_on_writer(settings, mocker):
    writer = "migration_other"
    user = get_user_model().objects.using(writer).create(username="synthetic-poster-editor")
    collection, _ = Collection.objects.using(writer).get_or_create(
        path="0001", defaults={"depth": 1, "numchild": 0, "name": "Synthetic"}
    )
    (video,) = Video.objects.using(writer).bulk_create(
        [Video(user=user, collection=collection, original="synthetic.mp4")]
    )

    class VideoRouter:
        def db_for_read(self, model, **hints):
            if model is Video:
                return "default"

        def db_for_write(self, model, **hints):
            if model is Video:
                return writer

    settings.DATABASE_ROUTERS = [VideoRouter()]
    assert not Video.objects.exists()

    def generate(instance):
        instance.poster.name = "synthetic-poster.jpg"

    mocker.patch.object(Video, "_create_poster", generate)
    progress = mocker.spy(recalc_video_posters, "track")
    output = StringIO()
    call_command("recalc_video_posters", stdout=output, stderr=StringIO())

    assert "processed=1 errors=0" in output.getvalue()
    assert progress.call_args.kwargs["total"] == 1
    video.refresh_from_db(using=writer)
    assert video.poster.name == "synthetic-poster.jpg"


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


@pytest.mark.django_db
@pytest.mark.parametrize("invalid_frame", [b"", b"not an image"])
def test_video_poster_skips_invalid_frame_and_can_retry(video, mocker, invalid_frame):
    stored_original = video.original.name
    video.poster = ""
    video.save(poster=False)
    mocker.patch.object(Video, "_get_video_dimensions", return_value=(2, 2))
    attempt_paths = []

    def extract(command, **kwargs):
        frame = Path(command[-1])
        attempt_paths.append(frame)
        if len(attempt_paths) == 1:
            frame.write_bytes(invalid_frame)
        else:
            Image.new("RGB", (2, 2)).save(frame, "JPEG")
        return subprocess.CompletedProcess(command, 0)

    mocker.patch("cast.models.video.run_media_probe", side_effect=extract)
    video.create_poster()
    assert not video.poster
    assert not attempt_paths[0].exists()
    video.refresh_from_db()
    assert video.original.name == stored_original
    assert not video.poster

    video.publish_missing_poster()

    video.refresh_from_db()
    assert video.poster.storage.exists(video.poster.name)
    assert not attempt_paths[1].exists()


@pytest.mark.django_db
@pytest.mark.parametrize("cleanup", ["unreferenced", "referenced", "delete-fails"])
def test_interrupted_poster_publication_retires_only_unreferenced_attempt(video, tmp_path, mocker, cleanup):
    storage = FileSystemStorage(location=tmp_path)
    mocker.patch.object(Video._meta.get_field("poster"), "storage", storage)
    editor_file = storage.save("editor.jpg", ContentFile(b"editor"))
    video.poster = ""
    video.save(poster=False)
    cancellation = KeyboardInterrupt("cancel before publication")

    def create(instance):
        instance.poster.save("attempt.jpg", ContentFile(b"attempt"), save=False)
        editor_choice = instance.poster.name if cleanup == "referenced" else editor_file
        Video.objects.filter(pk=instance.pk).update(poster=editor_choice)
        mocker.patch("django.db.models.query.QuerySet.update", side_effect=cancellation)
        if cleanup == "delete-fails":
            mocker.patch.object(storage, "delete", side_effect=OSError("synthetic storage failure"))

    mocker.patch.object(Video, "_create_poster", create)
    with pytest.raises(KeyboardInterrupt) as interrupted:
        video.publish_missing_poster()

    assert interrupted.value is cancellation
    attempt = video.poster.name
    video.refresh_from_db()
    assert storage.exists(editor_file)
    assert video.poster.name == (attempt if cleanup == "referenced" else editor_file)
    assert storage.exists(attempt) == (cleanup != "unreferenced")
    if cleanup == "delete-fails":
        assert interrupted.value.__notes__ == ["Could not retire the staged video poster"]


@pytest.mark.django_db
@pytest.mark.parametrize(("stream", "method"), [("stderr", "write"), ("stdout", "write"), ("stdout", "flush")])
def test_recalc_retains_published_posters_on_receipt_failure(video, tmp_path, mocker, stream, method):
    storage = FileSystemStorage(location=tmp_path)
    mocker.patch.object(Video._meta.get_field("poster"), "storage", storage)
    second, third = Video.objects.bulk_create(
        [Video(user=video.user, collection=video.collection, original=f"synthetic-{index}.mp4") for index in range(2)]
    )
    attempts = []

    def generate(item):
        attempts.append(item.pk)
        if item.pk == second.pk:
            raise RuntimeError("PRIVATE_MEDIA_ERROR")
        item.poster.save(f"{item.pk}.jpg", ContentFile(b"synthetic poster"), save=False)

    mocker.patch.object(Video, "_create_poster", generate)
    outputs = {"stdout": StringIO(), "stderr": StringIO()}
    mocker.patch.object(outputs[stream], method, side_effect=BrokenPipeError("PRIVATE_SINK_ERROR"))
    expected = "diagnostic failed: processed=2" if stream == "stderr" else "summary failed: processed=3"

    with pytest.raises(CommandError, match=f"Poster backfill {expected} errors=1") as error:
        call_command("recalc_video_posters", **outputs)

    assert "PRIVATE_" not in str(error.value) + outputs["stderr"].getvalue()
    assert attempts == ([video.pk, second.pk] if stream == "stderr" else [video.pk, second.pk, third.pk])
    for item in (video, second, third):
        item.refresh_from_db()
    assert storage.exists(video.poster.name)
    assert not second.poster
    if stream == "stderr":
        assert not third.poster
    else:
        assert storage.exists(third.poster.name)
        assert f"error recalculating poster for video {second.pk}:" in outputs["stderr"].getvalue()


@pytest.mark.django_db
def test_recalc_preserves_progress_when_terminal_rendering_breaks(video, tmp_path, mocker, monkeypatch):
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("TTY_COMPATIBLE", "1")
    storage = FileSystemStorage(location=tmp_path)
    mocker.patch.object(Video._meta.get_field("poster"), "storage", storage)
    (later,) = Video.objects.bulk_create(
        [Video(user=video.user, collection=video.collection, original="synthetic-later.mp4")]
    )
    attempts = []

    def generate(item):
        attempts.append(item.pk)
        item.poster.save("attempt.jpg", ContentFile(b"synthetic poster"), save=False)

    mocker.patch.object(Video, "_create_poster", generate)
    stdout = StringIO()
    mocker.patch.object(stdout, "isatty", return_value=True)
    original_write = stdout.write

    def write(value):
        if attempts:
            raise BrokenPipeError("PRIVATE_TERMINAL_ERROR")
        return original_write(value)

    mocker.patch.object(stdout, "write", side_effect=write)
    with pytest.raises(CommandError, match="Poster backfill progress failed: processed=1 errors=0"):
        call_command("recalc_video_posters", stdout=stdout, stderr=StringIO())

    assert attempts == [video.pk]
    video.refresh_from_db()
    later.refresh_from_db()
    assert storage.exists(video.poster.name)
    assert not later.poster


@pytest.mark.django_db
def test_recalc_terminal_progress_redraws_without_extra_newlines(video, tmp_path, mocker, monkeypatch):
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("TTY_COMPATIBLE", "1")
    storage = FileSystemStorage(location=tmp_path)
    mocker.patch.object(Video._meta.get_field("poster"), "storage", storage)
    Video.objects.bulk_create(
        [Video(user=video.user, collection=video.collection, original=f"synthetic-{index}.mp4") for index in range(4)]
    )

    def generate(item):
        item.poster.save(f"{item.pk}.jpg", ContentFile(b"synthetic poster"), save=False)

    mocker.patch.object(Video, "_create_poster", generate)
    stdout = StringIO()
    mocker.patch.object(stdout, "isatty", return_value=True)

    call_command("recalc_video_posters", stdout=stdout, stderr=StringIO())

    output = stdout.getvalue()
    assert "Recalculating video posters" in output
    # Rich redraws the bar in place; only its final line and the summary end with a newline.
    assert output.count("\n") == 2
    assert output.endswith("processed=5 errors=0\n")
