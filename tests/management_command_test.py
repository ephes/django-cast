from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.core.files.storage import storages
from django.core.exceptions import ObjectDoesNotExist
from django.core.management import CommandError, call_command

from cast.devdata import create_transcript
from cast.management.commands.media_backup import Command as MediaBackupCommand
from cast.management.commands.media_stale import Command as MediaStaleCommand
from cast.voxhelm import TranscriptGenerationResult, VoxhelmError

from .factories import BlogFactory
from .multisite_helpers import create_site_root


def test_media_backup_without_storages(settings):
    settings.STORAGES = {}
    with pytest.raises(CommandError) as err:
        call_command("media_backup")
    assert str(err.value) == "production or backup storage not configured"


def _stub_styleguide_prefetch(mocker, *, default_theme="plain", available_themes=None):
    if available_themes is None:
        available_themes = [("plain", "Plain")]

    mocker.patch(
        "cast.management.commands.styleguide_prefetch.get_template_base_dir_choices",
        return_value=available_themes,
    )
    styleguide_data = object()
    build_styleguide_data = mocker.patch(
        "cast.management.commands.styleguide_prefetch._build_styleguide_data",
        return_value=styleguide_data,
    )
    render_styleguide_context = mocker.patch("cast.management.commands.styleguide_prefetch._styleguide_context")
    default_theme_mock = mocker.patch(
        "cast.management.commands.styleguide_prefetch._styleguide_default_theme",
        return_value=default_theme,
    )
    return styleguide_data, build_styleguide_data, render_styleguide_context, default_theme_mock


class StubStorage:
    def __init__(self) -> None:
        self._files: dict[str, BytesIO] = {}
        self._added: set[str] = set()

    def exists(self, path: str) -> bool:
        return path in self._files

    def was_added_by_backup(self, name: str) -> bool:
        return name in self._added

    def was_not_added_by_backup(self, name: str) -> bool:
        return name not in self._added

    def save(self, name: str, content: BytesIO) -> None:
        self.save_without_adding(name, content)
        self._added.add(name)

    def save_without_adding(self, name: str, content: BytesIO) -> None:
        self._files[name] = content

    def listdir(self, _path: str) -> tuple[list, dict[str, BytesIO]]:
        return [], self._files

    @contextmanager
    def open(self, name: str, _mode: str) -> Iterator[BytesIO]:
        try:
            yield self._files[name]
        finally:
            pass


class StubProductionStorage:
    def __init__(self) -> None:
        self._files: dict[str, bytes] = {}
        self.deleted: list[str] = []
        self.saved: list[str] = []

    def exists(self, path: str) -> bool:
        return path in self._files

    def delete(self, path: str) -> None:
        self.deleted.append(path)
        self._files.pop(path, None)

    def save(self, path: str, content: BytesIO) -> str:
        self.saved.append(path)
        self._files[path] = content.read()
        return path

    def add(self, path: str, content: bytes) -> None:
        self._files[path] = content


class StubLocalStorage:
    def __init__(self, files: dict[str, bytes]) -> None:
        self._files = files

    def exists(self, path: str) -> bool:
        return path in self._files

    @contextmanager
    def open(self, name: str, _mode: str) -> Iterator[BytesIO]:
        yield BytesIO(self._files[name])


class StubWalkStorage:
    def __init__(self, files: dict[str, bytes]) -> None:
        self._files = files
        self.deleted: list[str] = []

    def listdir(self, _path: str) -> tuple[list[str], list[str]]:
        return [], list(self._files.keys())

    def size(self, path: str) -> int:
        return len(self._files[path])

    def delete(self, path: str) -> None:
        self.deleted.append(path)


@pytest.fixture
def stub_storages(settings):
    storage_stub = {"BACKEND": "tests.management_command_test.StubStorage"}
    settings.STORAGES = {"production": storage_stub, "backup": storage_stub}
    return storages


def test_media_backup_new_file_in_production(stub_storages):
    production, backup = stub_storages["production"], stub_storages["backup"]

    # given there's a new file added to production
    production.save_without_adding("foobar.jpg", BytesIO(b"foobar"))  # type: ignore

    # when we run the backup command
    call_command("media_backup")

    # then the file should have been added by the backup command
    assert backup.was_added_by_backup("foobar.jpg")  # type: ignore


def test_media_backup_existing_file_in_backup(stub_storages):
    production, backup = stub_storages["production"], stub_storages["backup"]

    # given there's a file in the backup
    production.save_without_adding("foobar.jpg", BytesIO(b"foobar"))  # type: ignore
    backup.save_without_adding("foobar.jpg", BytesIO(b"foobar"))  # type: ignore

    # when we run the backup method
    MediaBackupCommand().backup_media_files(production, backup)

    # then the file should not have been added by the backup command
    assert backup.was_not_added_by_backup("foobar.jpg")  # type: ignore


def test_media_replace_requires_explicit_confirmation(mocker):
    output = StringIO()
    production = StubProductionStorage()
    production.add("foo.jpg", b"old")
    local = StubLocalStorage({"foo.jpg": b"new"})
    mocker.patch(
        "cast.management.commands.media_replace.get_production_and_backup_storage",
        return_value=(production, object()),
    )
    mocker.patch("cast.management.commands.media_replace.FileSystemStorage", return_value=local)

    with pytest.raises(CommandError, match="Use --yes"):
        call_command("media_replace", "foo.jpg", stdout=output)

    assert production.deleted == []
    assert production.saved == []
    assert "No files were changed" in output.getvalue()


def test_media_replace_dry_run_does_not_write(mocker):
    output = StringIO()
    production = StubProductionStorage()
    production.add("foo.jpg", b"old")
    local = StubLocalStorage({"foo.jpg": b"new"})
    mocker.patch(
        "cast.management.commands.media_replace.get_production_and_backup_storage",
        return_value=(production, object()),
    )
    mocker.patch("cast.management.commands.media_replace.FileSystemStorage", return_value=local)

    call_command("media_replace", "foo.jpg", dry_run=True, stdout=output)

    assert production.deleted == []
    assert production.saved == []
    text = output.getvalue()
    assert "DRY RUN" in text
    assert "would replace: foo.jpg" in text
    assert "planned=1 replaced=0 skipped=0 errors=0" in text


def test_media_replace_yes_replaces_and_logs_summary(mocker):
    output = StringIO()
    production = StubProductionStorage()
    production.add("foo.jpg", b"old")
    local = StubLocalStorage({"foo.jpg": b"new"})
    mocker.patch(
        "cast.management.commands.media_replace.get_production_and_backup_storage",
        return_value=(production, object()),
    )
    mocker.patch("cast.management.commands.media_replace.FileSystemStorage", return_value=local)

    call_command("media_replace", "foo.jpg", yes=True, stdout=output)

    assert production.deleted == ["foo.jpg"]
    assert production.saved == ["foo.jpg"]
    text = output.getvalue()
    assert "replaced: foo.jpg" in text
    assert "planned=1 replaced=1 skipped=0 errors=0" in text


def test_media_replace_summary_includes_skipped(mocker):
    output = StringIO()
    production = StubProductionStorage()
    local = StubLocalStorage({"ok.jpg": b"new"})
    mocker.patch(
        "cast.management.commands.media_replace.get_production_and_backup_storage",
        return_value=(production, object()),
    )
    mocker.patch("cast.management.commands.media_replace.FileSystemStorage", return_value=local)

    call_command("media_replace", "missing.jpg", "ok.jpg", dry_run=True, stdout=output)

    text = output.getvalue()
    assert "skipped (not found locally): missing.jpg" in text
    assert "would replace: ok.jpg" in text
    assert "planned=1 replaced=0 skipped=1 errors=0" in text


def test_media_replace_yes_saves_when_target_is_missing_in_production(mocker):
    output = StringIO()
    production = StubProductionStorage()
    local = StubLocalStorage({"foo.jpg": b"new"})
    mocker.patch(
        "cast.management.commands.media_replace.get_production_and_backup_storage",
        return_value=(production, object()),
    )
    mocker.patch("cast.management.commands.media_replace.FileSystemStorage", return_value=local)

    call_command("media_replace", "foo.jpg", yes=True, stdout=output)

    assert production.deleted == []
    assert production.saved == ["foo.jpg"]


def test_media_replace_without_yes_and_only_missing_paths_does_not_error(mocker):
    output = StringIO()
    production = StubProductionStorage()
    local = StubLocalStorage({})
    mocker.patch(
        "cast.management.commands.media_replace.get_production_and_backup_storage",
        return_value=(production, object()),
    )
    mocker.patch("cast.management.commands.media_replace.FileSystemStorage", return_value=local)

    call_command("media_replace", "missing.jpg", stdout=output)

    text = output.getvalue()
    assert "Use --yes" not in text
    assert "planned=0 replaced=0 skipped=1 errors=0" in text


@pytest.mark.django_db
def test_media_stale_get_models_paths_includes_all_managed_media(audio, video, file_instance):
    transcript = create_transcript(
        audio=audio,
        podlove={"transcripts": []},
        vtt="WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello\n",
        dote={"lines": []},
    )
    paths = MediaStaleCommand().get_models_paths()

    assert audio.m4a.name in paths
    assert transcript.podlove.name in paths
    assert transcript.vtt.name in paths
    assert transcript.dote.name in paths
    assert video.original.name in paths
    assert file_instance.original.name in paths


@pytest.mark.django_db
def test_media_stale_get_image_paths_includes_renditions(image):
    rendition = image.get_rendition("fill-1x1")

    paths = MediaStaleCommand.get_image_paths()

    assert image.file.name in paths
    assert rendition.file.name in paths


def test_media_stale_handle_reports_and_deletes_stale_files(mocker, capsys):
    production = StubWalkStorage({"keep.jpg": b"keep", "stale.jpg": b"stale"})
    mocker.patch(
        "cast.management.commands.media_stale.get_production_and_backup_storage",
        return_value=(production, object()),
    )
    mocker.patch.object(MediaStaleCommand, "get_models_paths", return_value={"keep.jpg"})

    call_command("media_stale", delete=True)

    assert production.deleted == ["stale.jpg"]
    text = capsys.readouterr().out
    assert "stale production" in text
    assert "stale.jpg" in text


def test_media_stale_handle_without_delete_keeps_stale_files(mocker):
    production = StubWalkStorage({"stale.jpg": b"stale"})
    mocker.patch(
        "cast.management.commands.media_stale.get_production_and_backup_storage",
        return_value=(production, object()),
    )
    mocker.patch.object(MediaStaleCommand, "get_models_paths", return_value=set())

    call_command("media_stale")

    assert production.deleted == []


def test_media_stale_parser_registers_delete_flag():
    parser = MediaStaleCommand().create_parser("manage.py", "media_stale")
    option_strings = {option for action in parser._actions for option in action.option_strings}
    assert "--delete" in option_strings


@pytest.mark.django_db
def test_sync_renditions_rejects_ambiguous_blog_slug(user):
    _site1, site1_root = create_site_root(
        owner=user, hostname="sync-site1.local", slug="sync-site1-root", title="Sync Site 1"
    )
    _site2, site2_root = create_site_root(
        owner=user, hostname="sync-site2.local", slug="sync-site2-root", title="Sync Site 2"
    )
    BlogFactory(owner=user, title="Blog 1", slug="shared-sync-blog", parent=site1_root)
    BlogFactory(owner=user, title="Blog 2", slug="shared-sync-blog", parent=site2_root)

    with pytest.raises(CommandError, match="Multiple blogs found"):
        call_command("sync_renditions", blog_slug="shared-sync-blog")


@pytest.mark.django_db
def test_sync_renditions_rejects_missing_blog_slug():
    with pytest.raises(CommandError, match="No blog found"):
        call_command("sync_renditions", blog_slug="missing-blog")


@pytest.mark.django_db
def test_sync_renditions_with_post_slug_deletes_obsolete_and_builds_missing(mocker, post, image):
    filter_qs = mocker.patch("cast.management.commands.sync_renditions.Rendition.objects.filter")
    filter_qs.return_value.delete.return_value = None
    get_missing = mocker.patch(
        "cast.management.commands.sync_renditions.get_obsolete_and_missing_rendition_strings",
        return_value=([123], {image.id: ["fill-1x1"]}),
    )
    mocker.patch("cast.management.commands.sync_renditions.track", side_effect=lambda items, description=None: items)
    image_get = mocker.patch("cast.management.commands.sync_renditions.Image.objects.get", return_value=image)
    get_renditions = mocker.patch.object(image, "get_renditions")

    call_command("sync_renditions", post_slug=post.slug)

    get_missing.assert_called_once()
    filter_qs.assert_called_once_with(id__in=[123])
    image_get.assert_called_once_with(id=image.id)
    get_renditions.assert_called_once_with("fill-1x1")


@pytest.mark.django_db
def test_sync_renditions_with_unique_blog_slug_syncs_descendants(mocker, blog, post, image):
    filter_qs = mocker.patch("cast.management.commands.sync_renditions.Rendition.objects.filter")
    filter_qs.return_value.delete.return_value = None
    mocker.patch(
        "cast.management.commands.sync_renditions.get_obsolete_and_missing_rendition_strings",
        return_value=([321], {image.id: ["fill-2x2"]}),
    )
    mocker.patch("cast.management.commands.sync_renditions.track", side_effect=lambda items, description=None: items)
    mocker.patch("cast.management.commands.sync_renditions.Image.objects.get", return_value=image)
    get_renditions = mocker.patch.object(image, "get_renditions")

    call_command("sync_renditions", blog_slug=blog.slug)

    filter_qs.assert_called_once_with(id__in=[321])
    get_renditions.assert_called_once_with("fill-2x2")


@pytest.mark.django_db
def test_sync_renditions_without_filters_uses_all_posts(mocker):
    mocked_queryset = mocker.Mock()
    mocked_queryset.prefetch_related.return_value = mocked_queryset
    all_posts = mocker.patch("cast.management.commands.sync_renditions.Post.objects.all", return_value=mocked_queryset)
    mocker.patch("cast.management.commands.sync_renditions.Post.get_all_images_from_queryset", return_value=iter(()))
    mocker.patch(
        "cast.management.commands.sync_renditions.get_obsolete_and_missing_rendition_strings",
        return_value=([], {}),
    )
    mocker.patch("cast.management.commands.sync_renditions.Rendition.objects.filter")
    mocker.patch("cast.management.commands.sync_renditions.track", side_effect=lambda items, description=None: items)

    call_command("sync_renditions")

    all_posts.assert_called_once_with()


def test_media_replace_dry_run_with_yes_warns_and_does_not_write(mocker):
    output = StringIO()
    error_output = StringIO()
    production = StubProductionStorage()
    production.add("foo.jpg", b"old")
    local = StubLocalStorage({"foo.jpg": b"new"})
    mocker.patch(
        "cast.management.commands.media_replace.get_production_and_backup_storage",
        return_value=(production, object()),
    )
    mocker.patch("cast.management.commands.media_replace.FileSystemStorage", return_value=local)

    call_command("media_replace", "foo.jpg", dry_run=True, yes=True, stdout=output, stderr=error_output)

    assert production.deleted == []
    assert production.saved == []
    assert "--yes is ignored in dry-run mode" in error_output.getvalue()


def test_media_replace_dry_run_with_yes_warns_once_for_multiple_files(mocker):
    output = StringIO()
    error_output = StringIO()
    production = StubProductionStorage()
    production.add("foo.jpg", b"old")
    production.add("bar.jpg", b"old")
    local = StubLocalStorage({"foo.jpg": b"new", "bar.jpg": b"new"})
    mocker.patch(
        "cast.management.commands.media_replace.get_production_and_backup_storage",
        return_value=(production, object()),
    )
    mocker.patch("cast.management.commands.media_replace.FileSystemStorage", return_value=local)

    call_command(
        "media_replace",
        "foo.jpg",
        "bar.jpg",
        dry_run=True,
        yes=True,
        stdout=output,
        stderr=error_output,
    )

    assert error_output.getvalue().count("--yes is ignored in dry-run mode") == 1


def test_media_replace_logs_error_and_summary_when_save_fails(mocker):
    output = StringIO()
    error_output = StringIO()
    production = StubProductionStorage()
    local = StubLocalStorage({"foo.jpg": b"new"})
    mocker.patch(
        "cast.management.commands.media_replace.get_production_and_backup_storage",
        return_value=(production, object()),
    )
    mocker.patch("cast.management.commands.media_replace.FileSystemStorage", return_value=local)
    mocker.patch.object(production, "save", side_effect=RuntimeError("boom"))

    call_command("media_replace", "foo.jpg", yes=True, stdout=output, stderr=error_output)

    assert "error replacing foo.jpg: boom" in error_output.getvalue()
    assert "planned=1 replaced=0 skipped=0 errors=1" in output.getvalue()


def test_media_replace_logs_data_loss_risk_when_existing_file_delete_then_save_fails(mocker):
    output = StringIO()
    error_output = StringIO()
    production = StubProductionStorage()
    production.add("foo.jpg", b"old")
    local = StubLocalStorage({"foo.jpg": b"new"})
    mocker.patch(
        "cast.management.commands.media_replace.get_production_and_backup_storage",
        return_value=(production, object()),
    )
    mocker.patch("cast.management.commands.media_replace.FileSystemStorage", return_value=local)
    mocker.patch.object(production, "save", side_effect=RuntimeError("boom"))

    call_command("media_replace", "foo.jpg", yes=True, stdout=output, stderr=error_output)

    assert production.deleted == ["foo.jpg"]
    assert "error replacing foo.jpg: boom" in error_output.getvalue()
    assert "may have been deleted before save failed" in error_output.getvalue()


def test_media_replace_warns_when_storage_returns_different_saved_name(mocker):
    output = StringIO()
    error_output = StringIO()
    production = StubProductionStorage()
    local = StubLocalStorage({"foo.jpg": b"new"})
    mocker.patch(
        "cast.management.commands.media_replace.get_production_and_backup_storage",
        return_value=(production, object()),
    )
    mocker.patch("cast.management.commands.media_replace.FileSystemStorage", return_value=local)
    mocker.patch.object(production, "save", return_value="foo_1.jpg")

    call_command("media_replace", "foo.jpg", yes=True, stdout=output, stderr=error_output)

    assert "warning: foo.jpg saved as foo_1.jpg" in error_output.getvalue()


def test_recalc_video_posters_continues_after_error_and_reports_summary(mocker):
    output = StringIO()
    error_output = StringIO()
    first = Mock(pk=1)
    first.create_poster.side_effect = RuntimeError("boom")
    second = Mock(pk=2)
    videos = [first, second]
    manager = mocker.Mock()
    manager.all.return_value.order_by.return_value = videos
    mocker.patch("cast.management.commands.recalc_video_posters.Video.objects", manager)
    mocker.patch("cast.management.commands.recalc_video_posters.track", side_effect=lambda iterable, **_: iterable)

    call_command("recalc_video_posters", stdout=output, stderr=error_output)

    first.create_poster.assert_called_once_with()
    first.save.assert_not_called()
    second.create_poster.assert_called_once_with()
    second.save.assert_called_once_with(poster=False)
    assert "error recalculating poster for video 1: boom" in error_output.getvalue()
    assert "processed=2 errors=1" in output.getvalue()


def test_recalc_video_posters_reports_zero_processed(mocker):
    output = StringIO()
    manager = mocker.Mock()
    manager.all.return_value.order_by.return_value = []
    mocker.patch("cast.management.commands.recalc_video_posters.Video.objects", manager)
    mocker.patch("cast.management.commands.recalc_video_posters.track", side_effect=lambda iterable, **_: iterable)

    call_command("recalc_video_posters", stdout=output)

    assert "processed=0 errors=0" in output.getvalue()


def test_styleguide_prefetch_command(settings, mocker):
    styleguide_data, build_styleguide_data, render_styleguide_context, _default_theme = _stub_styleguide_prefetch(
        mocker
    )

    call_command("styleguide_prefetch", theme="plain")
    request = build_styleguide_data.call_args.args[0]
    assert request.path == "/cast/styleguide/"
    render_styleguide_context.assert_called_once_with(styleguide_data, request, "plain")


def test_styleguide_prefetch_command_default_theme(settings, mocker):
    styleguide_data, build_styleguide_data, render_styleguide_context, default_theme = _stub_styleguide_prefetch(
        mocker
    )

    call_command("styleguide_prefetch")
    request = build_styleguide_data.call_args.args[0]
    default_theme.assert_called_once_with()
    render_styleguide_context.assert_called_once_with(styleguide_data, request, "plain")


def test_styleguide_prefetch_command_invalid_theme(settings, mocker):
    mocker.patch(
        "cast.management.commands.styleguide_prefetch.get_template_base_dir_choices",
        return_value=[("plain", "Plain")],
    )
    with pytest.raises(CommandError):
        call_command("styleguide_prefetch", theme="not-a-theme")


def test_styleguide_prefetch_command_with_renditions(settings, mocker):
    settings.CAST_STYLEGUIDE_GENERATE_RENDITIONS = False
    styleguide_data, build_styleguide_data, render_styleguide_context, _default_theme = _stub_styleguide_prefetch(
        mocker
    )

    call_command("styleguide_prefetch", theme="plain", with_renditions=True)
    request = build_styleguide_data.call_args.args[0]
    render_styleguide_context.assert_called_once_with(styleguide_data, request, "plain")
    assert settings.CAST_STYLEGUIDE_GENERATE_RENDITIONS is True


def test_generate_transcripts_requires_targets():
    with pytest.raises(CommandError, match="Provide at least one --episode-id or --audio-id"):
        call_command("generate_transcripts")


def test_generate_transcripts_get_existing_transcript_handles_missing_relation():
    class MissingTranscriptAudio:
        @property
        def transcript(self):
            raise ObjectDoesNotExist

    from cast.management.commands.generate_transcripts import Command

    assert Command._get_existing_transcript(audio=MissingTranscriptAudio()) is None


def test_generate_transcripts_rejects_unknown_episode_id(mocker):
    queryset = mocker.Mock()
    queryset.select_related.return_value = queryset
    queryset.order_by.return_value = []
    mocker.patch("cast.management.commands.generate_transcripts.Episode.objects.filter", return_value=queryset)

    with pytest.raises(CommandError, match="Unknown episode id"):
        call_command("generate_transcripts", "--episode-id", "7")


@pytest.mark.django_db
def test_generate_transcripts_rejects_unknown_audio_id():
    with pytest.raises(CommandError, match="Unknown audio id"):
        call_command("generate_transcripts", "--audio-id", "999999")


@pytest.mark.django_db
def test_generate_transcripts_rejects_episode_without_audio(mocker):
    queryset = mocker.Mock()
    queryset.select_related.return_value = queryset
    queryset.order_by.return_value = [SimpleNamespace(pk=1, podcast_audio_id=None)]
    mocker.patch("cast.management.commands.generate_transcripts.Episode.objects.filter", return_value=queryset)

    with pytest.raises(CommandError, match="has no podcast audio"):
        call_command("generate_transcripts", "--episode-id", "1")


@pytest.mark.django_db
def test_generate_transcripts_skips_complete_transcript(mocker, audio):
    create_transcript(
        audio=audio,
        podlove={"transcripts": [{"text": "existing"}]},
        vtt="WEBVTT\n\n00:00:00.000 --> 00:00:00.500\nexisting\n",
        dote={
            "lines": [
                {
                    "startTime": "00:00:00,000",
                    "endTime": "00:00:00,500",
                    "speakerDesignation": "",
                    "text": "existing",
                }
            ]
        },
    )
    service_cls = mocker.patch("cast.management.commands.generate_transcripts.VoxhelmTranscriptService")
    output = StringIO()

    call_command("generate_transcripts", "--audio-id", str(audio.pk), stdout=output)

    assert "skipped audio=" in output.getvalue()
    assert "processed=1 created=0 updated=0 skipped=1 errors=0" in output.getvalue()
    service_cls.return_value.generate_for_audio.assert_not_called()


@pytest.mark.django_db
def test_generate_transcripts_does_not_skip_empty_transcript(mocker, audio):
    transcript = create_transcript(
        audio=audio,
        podlove={"transcripts": []},
        vtt="WEBVTT\n\n",
        dote={"lines": []},
    )
    service = mocker.Mock()
    service.generate_for_audio.return_value = TranscriptGenerationResult(
        transcript=transcript,
        created=False,
        job_id="job-789",
        source_url="https://media.example.com/episode.m4a",
    )
    mocker.patch(
        "cast.management.commands.generate_transcripts.VoxhelmTranscriptService",
        return_value=service,
    )
    output = StringIO()

    call_command("generate_transcripts", "--audio-id", str(audio.pk), stdout=output)

    assert "skipped audio=" not in output.getvalue()
    assert "updated audio=" in output.getvalue()
    service.generate_for_audio.assert_called_once_with(audio, task_ref=f"cast-audio-{audio.pk}", episode=None)


@pytest.mark.django_db
def test_generate_transcripts_calls_service_for_episode(mocker, audio):
    transcript = create_transcript(audio=audio)
    queryset = mocker.Mock()
    queryset.select_related.return_value = queryset
    episode = SimpleNamespace(pk=7, podcast_audio_id=audio.pk, podcast_audio=audio)
    queryset.order_by.return_value = [episode]
    mocker.patch("cast.management.commands.generate_transcripts.Episode.objects.filter", return_value=queryset)
    service = mocker.Mock()
    service.generate_for_audio.return_value = TranscriptGenerationResult(
        transcript=transcript,
        created=True,
        job_id="job-123",
        source_url="https://media.example.com/episode.m4a",
    )
    service_cls = mocker.patch(
        "cast.management.commands.generate_transcripts.VoxhelmTranscriptService",
        return_value=service,
    )
    output = StringIO()

    call_command("generate_transcripts", "--episode-id", "7", stdout=output)

    assert "created audio=" in output.getvalue()
    assert "job=job-123" in output.getvalue()
    assert "processed=1 created=1 updated=0 skipped=0 errors=0" in output.getvalue()
    service_cls.assert_called_once_with()
    service.generate_for_audio.assert_called_once()
    called_audio = service.generate_for_audio.call_args.args[0]
    assert called_audio.pk == audio.pk
    assert service.generate_for_audio.call_args.kwargs["episode"] == episode


@pytest.mark.django_db
def test_generate_transcripts_force_updates_and_uses_unique_task_ref(mocker, audio):
    transcript = create_transcript(audio=audio)
    service = mocker.Mock()
    service.generate_for_audio.return_value = TranscriptGenerationResult(
        transcript=transcript,
        created=False,
        job_id="job-456",
        source_url="https://media.example.com/episode.m4a",
    )
    mocker.patch(
        "cast.management.commands.generate_transcripts.VoxhelmTranscriptService",
        return_value=service,
    )
    output = StringIO()

    call_command("generate_transcripts", "--audio-id", str(audio.pk), "--force", stdout=output)

    assert "updated audio=" in output.getvalue()
    task_ref = service.generate_for_audio.call_args.kwargs["task_ref"]
    assert task_ref.startswith(f"cast-audio-{audio.pk}-")


@pytest.mark.django_db
def test_generate_transcripts_reports_errors_and_raises(mocker, audio):
    service = mocker.Mock()
    service.generate_for_audio.side_effect = VoxhelmError("backend exploded")
    mocker.patch(
        "cast.management.commands.generate_transcripts.VoxhelmTranscriptService",
        return_value=service,
    )
    output = StringIO()
    error_output = StringIO()

    with pytest.raises(CommandError, match="1 transcript generations failed"):
        call_command("generate_transcripts", "--audio-id", str(audio.pk), stdout=output, stderr=error_output)

    assert "error audio=" in error_output.getvalue()
    assert "processed=1 created=0 updated=0 skipped=0 errors=1" in output.getvalue()


def test_generate_transcripts_resolve_targets_skips_duplicates_and_unsaved(mocker):
    from cast.management.commands.generate_transcripts import Command

    shared_audio = SimpleNamespace(pk=5)
    episode_queryset = mocker.Mock()
    episode_queryset.select_related.return_value = episode_queryset
    episode_queryset.order_by.return_value = [SimpleNamespace(pk=1, podcast_audio_id=5, podcast_audio=shared_audio)]
    direct_queryset = mocker.Mock()
    direct_queryset.select_related.return_value = direct_queryset
    direct_queryset.order_by.return_value = [shared_audio, SimpleNamespace(pk=None)]
    mocker.patch("cast.management.commands.generate_transcripts.Episode.objects.filter", return_value=episode_queryset)
    mocker.patch("cast.management.commands.generate_transcripts.Audio.objects.filter", return_value=direct_queryset)

    targets = Command()._resolve_targets(episode_ids=[1], audio_ids=[5])

    assert [target.audio for target in targets] == [shared_audio]
    assert targets[0].episode.pk == 1


def test_generate_transcripts_resolve_targets_skips_unsaved_episode_audio(mocker):
    from cast.management.commands.generate_transcripts import Command

    episode_queryset = mocker.Mock()
    episode_queryset.select_related.return_value = episode_queryset
    episode_queryset.order_by.return_value = [
        SimpleNamespace(pk=1, podcast_audio_id=7, podcast_audio=SimpleNamespace(pk=None))
    ]
    direct_queryset = mocker.Mock()
    direct_queryset.select_related.return_value = direct_queryset
    direct_queryset.order_by.return_value = []
    mocker.patch("cast.management.commands.generate_transcripts.Episode.objects.filter", return_value=episode_queryset)
    mocker.patch("cast.management.commands.generate_transcripts.Audio.objects.filter", return_value=direct_queryset)

    assert Command()._resolve_targets(episode_ids=[1], audio_ids=[]) == []
