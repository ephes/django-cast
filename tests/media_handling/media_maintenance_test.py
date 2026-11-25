"""Synthetic media inventories and files exercise maintenance boundaries."""

from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from wagtail.images.models import Image, Rendition

from cast.management.commands.storage_backend import sync_media_files
from cast.models import Blog, Post
from tests.factories import BlogFactory
from tests.management_command_helpers import StubOverwriteStorage


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

    def plan(images, *, using, check_files=False):
        assert check_files
        seen.extend(images)
        return set(), {}

    mocker.patch(
        "cast.management.commands.sync_renditions.get_obsolete_and_missing_rendition_strings", side_effect=plan
    )
    call_command("sync_renditions", post_slug=post.slug, blog_slug=blog.slug)
    assert [(kind, current.pk) for kind, current in seen] == [("regular", image.pk)]


@pytest.mark.django_db
def test_rendition_sync_pins_blog_in_one_select(mocker, blog, post, image):
    post.images.add(image)
    slug = blog.slug
    descendant_of = Post.objects.descendant_of

    def rename_before_work(selected_blog):
        assert selected_blog.pk == blog.pk
        Blog.objects.filter(pk=blog.pk).update(slug="renamed-sync-blog")
        return descendant_of(selected_blog)

    def plan(images, *, using, check_files):
        assert check_files
        assert [(kind, current.pk) for kind, current in images] == [("regular", image.pk)]
        return set(), {}

    mocker.patch.object(Post.objects, "descendant_of", side_effect=rename_before_work)
    mocker.patch(
        "cast.management.commands.sync_renditions.get_obsolete_and_missing_rendition_strings", side_effect=plan
    )
    with CaptureQueriesContext(connection) as queries:
        call_command("sync_renditions", blog_slug=slug)

    selection = [row["sql"] for row in queries if row["sql"].startswith("SELECT") and f"'{slug}'" in row["sql"]]
    assert len(selection) == 1
    assert "LIMIT 2" in selection[0]


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


@pytest.mark.django_db
def test_rendition_failure_retains_old_bytes_and_successful_retry_retires_only_counterpart(
    mocker, post, disk_image, django_capture_on_commit_callbacks
):
    image = disk_image
    post.images.add(image)
    old = image.get_rendition("width-1")
    unrelated = image.get_rendition("height-1")
    old_pk, old_path = old.pk, old.file.path
    original_bytes = Path(old_path).read_bytes()
    unrelated_path = unrelated.file.path
    mocker.patch(
        "cast.management.commands.sync_renditions.get_obsolete_and_missing_rendition_strings",
        return_value=({old_pk}, {image.pk: {"width-1|srgb"}}),
    )
    original_generate = Image.generate_rendition_file
    failing = mocker.patch.object(Image, "generate_rendition_file", side_effect=OSError("synthetic image failure"))
    with django_capture_on_commit_callbacks(execute=True), pytest.raises(OSError, match="synthetic image failure"):
        call_command("sync_renditions", post_slug=post.slug)
    failing.assert_called_once()
    assert Rendition.objects.filter(pk=old_pk).exists()
    assert Path(old_path).read_bytes() == original_bytes
    mocker.patch.object(Image, "generate_rendition_file", original_generate)
    with django_capture_on_commit_callbacks(execute=True):
        call_command("sync_renditions", post_slug=post.slug)
    assert not Rendition.objects.filter(pk=old_pk).exists()
    assert not image.file.storage.exists(old.file.name)
    assert Path(unrelated_path).read_bytes()
    new = image.renditions.get(filter_spec="width-1|srgb")
    assert new.file.storage.exists(new.file.name)


@pytest.mark.django_db
@pytest.mark.parametrize("fault", ["omitted", "unsaved", "missing-file", "empty-name"])
def test_rendition_verification_failure_keeps_obsolete_file(mocker, post, disk_image, fault):
    post.images.add(disk_image)
    old = disk_image.get_rendition("width-1")
    old_pk, old_name = old.pk, old.file.name
    mocker.patch(
        "cast.management.commands.sync_renditions.get_obsolete_and_missing_rendition_strings",
        return_value=({old_pk}, {disk_image.pk: {"width-1|srgb"}}),
    )
    replacement = Rendition(image=disk_image, filter_spec="width-1|srgb", file="missing.png", width=1, height=1)
    if fault in {"missing-file", "empty-name"}:
        if fault == "empty-name":
            replacement.file.name = ""
        replacement.save()
    mocker.patch("cast.management.commands.sync_renditions.repair_missing_rendition_files", return_value=set())
    mocker.patch("cast.management.commands.sync_renditions.create_rendition_with_receipt", return_value=replacement)
    with pytest.raises(CommandError, match="replacement"):
        call_command("sync_renditions", post_slug=post.slug)
    assert Rendition.objects.filter(pk=old_pk).exists()
    assert old.file.storage.exists(old_name)


@pytest.mark.django_db
def test_sync_discovers_shared_images_by_role_and_hydrates_in_batches(mocker, blog, post, image):
    from cast.models import Gallery

    other = Image.objects.create(title="Other", file=image.file.name, collection=image.collection)
    third = Image.objects.create(title="Third", file=image.file.name, collection=image.collection)
    gallery = Gallery.objects.create()
    gallery.images.add(image, other, third)
    for index in range(4):
        page = post if index == 0 else blog.add_child(instance=Post(title=f"Shared {index}"))
        page.images.add(image)
        page.galleries.add(gallery)

    mocker.patch("cast.management.commands.sync_renditions.BATCH_SIZE", 2, create=True)
    seen = []
    repaired = []

    def plan(images, **kwargs):
        variants = [(kind, item.pk) for kind, item in images]
        seen.extend(variants)
        return set(), {image_id: set() for _, image_id in variants}

    def repair(item, *args, **kwargs):
        repaired.append(item.pk)
        return set()

    mocker.patch("cast.management.commands.sync_renditions.get_obsolete_and_missing_rendition_strings", plan)
    mocker.patch("cast.management.commands.sync_renditions.repair_missing_rendition_files", repair)
    with CaptureQueriesContext(connection) as queries:
        call_command("sync_renditions", stdout=StringIO())

    assert sorted(seen) == sorted(
        [("regular", image.pk), ("gallery", image.pk), ("gallery", other.pk), ("gallery", third.pk)]
    )
    assert sorted(repaired) == sorted([image.pk, other.pk, third.pk])
    relation_table = Post.images.through._meta.db_table
    assert sum(f'JOIN "{relation_table}"' in q["sql"] for q in queries) == 2
    image_batches = [q["sql"] for q in queries if 'FROM "wagtailimages_image" WHERE' in q["sql"]]
    assert len(image_batches) == 4
    assert all(" IN (" in sql for sql in image_batches)


@pytest.mark.django_db
def test_disappeared_image_after_inventory_fails_before_rendition_retirement(mocker, post, disk_image):
    post.images.add(disk_image)
    image_id = disk_image.pk

    def plan(images, **kwargs):
        assert next(images)[1].pk == image_id
        disk_image.delete()
        return set(), {image_id: {"width-1"}}

    mocker.patch("cast.management.commands.sync_renditions.get_obsolete_and_missing_rendition_strings", plan)
    with pytest.raises(CommandError, match=rf"Images disappeared during rendition synchronization: \[{image_id}\]"):
        call_command("sync_renditions", post_slug=post.slug)
