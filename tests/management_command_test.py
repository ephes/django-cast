from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
from io import StringIO
from unittest.mock import Mock

import django
import pytest

try:
    from django.core.files.storage import storages
except ImportError:
    pass
from django.core.management import CommandError, call_command

try:
    from cast.management.commands.media_backup import Command as MediaBackupCommand
except ImportError:
    pass
from cast.devdata import create_transcript
from cast.management.commands.media_stale import Command as MediaStaleCommand

from .factories import BlogFactory
from .multisite_helpers import create_site_root


def get_comparable_django_version():
    django_version = "".join(django.get_version().split(".")[:2])
    try:
        return int(django_version)
    except ValueError:
        # pre-release probably
        return int(django_version.split("a")[0])


pytestmark = pytest.mark.skipif(
    get_comparable_django_version() < 42,
    reason="Django version >= 4.2 is required",
)


def test_media_backup_without_storages(settings):
    settings.STORAGES = {}
    with pytest.raises(CommandError) as err:
        call_command("media_backup")
    assert str(err.value) == "production or backup storage not configured"


def test_media_backup_with_wrong_django_version(mocker):
    mocker.patch("cast.management.commands.storage_backend.DJANGO_VERSION_VALID", False)
    with pytest.raises(CommandError) as err:
        call_command("media_backup")
    assert str(err.value) == "Django version >= 4.2 is required"


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
