"""Synthetic media inventories and files exercise maintenance boundaries."""

from io import StringIO
from pathlib import Path

import pytest
from django.core.files.storage import FileSystemStorage
from django.core.management import CommandError, call_command
from wagtail.images.models import Image, Rendition
from wagtail.models import Collection

from cast.management.commands.storage_backend import sync_media_files
from cast.models import Post
from tests.factories import BlogFactory
from tests.management_command_test import StubOverwriteStorage


@pytest.mark.parametrize("mode", ["backup", "refresh", "restore"])
def test_sync_skips_only_reserved_refresh_scratch_without_deleting_source(mocker, mode):
    reserved = "album/photo.jpg.django-cast-refresh-" + "a" * 32 + ".tmp"
    legitimate = {
        "album/photo.jpg": b"photo",
        "album/photo.jpg.django-cast-refresh-short.tmp": b"short",
        "album/photo.jpg.django-cast-refresh-" + "A" * 32 + ".tmp": b"uppercase",
        reserved + ".backup": b"suffix",
    }
    source = StubOverwriteStorage({reserved: b"partial", **legitimate})
    target = StubOverwriteStorage()
    command = "media_restore" if mode == "restore" else "media_backup"
    pair = (target, source) if mode == "restore" else (source, target)
    mocker.patch(f"cast.management.commands.{command}.get_production_and_backup_storage", return_value=pair)
    errors = StringIO()
    options = {"refresh_changed": True} if mode == "refresh" else {}
    call_command(command, stdout=StringIO(), stderr=errors, **options)
    assert target._files == legitimate
    assert source._files == {reserved: b"partial", **legitimate}
    assert source.deleted == []
    assert reserved in errors.getvalue()
    assert "skipped" in errors.getvalue()


def test_direct_sync_reports_reserved_leftover_without_error(caplog):
    reserved = "photo.jpg.django-cast-refresh-" + "0" * 32 + ".tmp"
    source, target = StubOverwriteStorage({reserved: b"partial"}), StubOverwriteStorage()
    result = sync_media_files(source, target, refresh_changed=True)
    assert result.errors == result.copied == result.refreshed == 0
    assert target._files == {}
    assert reserved in caplog.text


@pytest.mark.django_db
def test_combined_rendition_selectors_intersect_blog_and_post(mocker, blog, post, image):
    other_blog = BlogFactory(parent=blog.get_parent(), owner=blog.owner, slug="other-selector-blog", title="Other")
    other_post = other_blog.add_child(instance=Post(owner=blog.owner, title="Other post", slug=post.slug))
    post.images.add(image)
    other_post.images.add(image)
    seen = []

    def plan(images):
        seen.extend(images)
        return set(), {}

    mocker.patch(
        "cast.management.commands.sync_renditions.get_obsolete_and_missing_rendition_strings", side_effect=plan
    )
    call_command("sync_renditions", post_slug=post.slug, blog_slug=blog.slug)
    assert [(kind, current.pk) for kind, current in seen] == [("regular", image.pk)]


@pytest.mark.django_db
@pytest.mark.parametrize("selection", ["missing-blog", "missing-post", "empty-blog"])
def test_invalid_explicit_rendition_selection_fails_before_mutation(mocker, blog, post, selection):
    plan = mocker.patch(
        "cast.management.commands.sync_renditions.get_obsolete_and_missing_rendition_strings", return_value=(set(), {})
    )
    retire = mocker.patch("cast.management.commands.sync_renditions.Rendition.objects.filter")
    options = {"blog_slug": blog.slug, "post_slug": post.slug}
    if selection == "missing-blog":
        options["blog_slug"] = "missing-blog"
    elif selection == "missing-post":
        options["post_slug"] = "missing-post"
    else:
        empty = BlogFactory(parent=blog.get_parent(), owner=blog.owner, slug="empty-selector-blog", title="Empty")
        options = {"blog_slug": empty.slug}
    with pytest.raises(CommandError):
        call_command("sync_renditions", **options)
    plan.assert_not_called()
    retire.assert_not_called()


@pytest.fixture
def disk_image(db, tmp_path, image_1px, monkeypatch):
    storage = FileSystemStorage(location=str(tmp_path))
    monkeypatch.setattr(Image._meta.get_field("file"), "storage", storage)
    monkeypatch.setattr(Rendition._meta.get_field("file"), "storage", storage)
    collection = Collection.get_first_root_node() or Collection.add_root(instance=Collection(name="Root"))
    image = Image(title="Synthetic image", file=image_1px, collection=collection)
    image.save()
    return image


@pytest.mark.django_db
def test_rendition_failure_retains_old_bytes_and_successful_retry_retires_only_counterpart(
    mocker, post, disk_image, django_capture_on_commit_callbacks
):
    image = disk_image
    old = image.get_rendition("width-1")
    unrelated = image.get_rendition("height-1")
    old_pk, old_path = old.pk, old.file.path
    original_bytes = Path(old_path).read_bytes()
    unrelated_path = unrelated.file.path
    mocker.patch(
        "cast.management.commands.sync_renditions.get_obsolete_and_missing_rendition_strings",
        return_value=({old_pk}, {image.pk: {"fill-2x2"}}),
    )
    original_generate = Image.get_renditions
    failing = mocker.patch.object(Image, "get_renditions", side_effect=OSError("synthetic image failure"))
    with django_capture_on_commit_callbacks(execute=True), pytest.raises(OSError, match="synthetic image failure"):
        call_command("sync_renditions", post_slug=post.slug)
    failing.assert_called_once()
    assert Rendition.objects.filter(pk=old_pk).exists()
    assert Path(old_path).read_bytes() == original_bytes
    mocker.patch.object(Image, "get_renditions", original_generate)
    with django_capture_on_commit_callbacks(execute=True):
        call_command("sync_renditions", post_slug=post.slug)
    assert not Rendition.objects.filter(pk=old_pk).exists()
    assert not image.file.storage.exists(old.file.name)
    assert Path(unrelated_path).read_bytes()
    new = image.renditions.get(filter_spec="fill-2x2")
    assert new.file.storage.exists(new.file.name)


@pytest.mark.django_db
@pytest.mark.parametrize("fault", ["omitted", "unsaved", "missing-file", "empty-name"])
def test_rendition_verification_failure_keeps_obsolete_file(mocker, post, disk_image, fault):
    old = disk_image.get_rendition("width-1")
    old_pk, old_name = old.pk, old.file.name
    mocker.patch(
        "cast.management.commands.sync_renditions.get_obsolete_and_missing_rendition_strings",
        return_value=({old_pk}, {disk_image.pk: {"fill-2x2"}}),
    )
    replacement = Rendition(image=disk_image, filter_spec="fill-2x2", file="missing.png", width=1, height=1)
    if fault in {"missing-file", "empty-name"}:
        if fault == "empty-name":
            replacement.file.name = ""
        replacement.save()
    result = {} if fault == "omitted" else {"fill-2x2": replacement}
    mocker.patch.object(Image, "get_renditions", return_value=result)
    with pytest.raises(CommandError, match="replacement"):
        call_command("sync_renditions", post_slug=post.slug)
    assert Rendition.objects.filter(pk=old_pk).exists()
    assert old.file.storage.exists(old_name)
