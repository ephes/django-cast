"""Synthetic storage writes follow the rendition transaction outcome."""

import logging
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command
from wagtail.images.models import Filter, Image, Rendition


@pytest.mark.django_db
@pytest.mark.parametrize("first", ["repair", "create"])
@pytest.mark.parametrize("failure", ["generation", "verification"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_sync_compensates_completed_writes_after_rollback(
    post, disk_image, mocker, first, failure, cleanup_fails, caplog
):
    image = disk_image
    old = image.get_rendition("fill-1x1")
    old_bytes = Path(old.file.path).read_bytes()
    missing = image.get_rendition("width-1") if first == "repair" else None
    if missing:
        missing.file.storage.delete(missing.file.name)
    before_rows = list(image.renditions.order_by("pk").values_list("pk", "file"))
    before_files = {p for p in Path(image.file.storage.location).rglob("*") if p.is_file()}
    mocker.patch(
        "cast.management.commands.sync_renditions.get_obsolete_and_missing_rendition_strings",
        return_value=({old.pk}, {image.pk: ["width-1", "height-1"]}),
    )
    generate = Image.generate_rendition_file
    generated = []

    def generate_or_fail(self, filter, **kwargs):
        if failure == "generation" and generated:
            raise RuntimeError("synthetic later failure")
        result = generate(self, filter, **kwargs)
        generated.append(result)
        return result

    mocker.patch.object(Image, "generate_rendition_file", generate_or_fail)
    storage = Rendition._meta.get_field("file").storage
    exists = storage.exists

    def verify_or_fail(name):
        if (
            failure == "verification"
            and len(generated) == 2
            and image.renditions.filter(filter_spec__in=["width-1", "height-1"]).count() == 2
        ):
            raise RuntimeError("synthetic later failure")
        return exists(name)

    mocker.patch.object(storage, "exists", side_effect=verify_or_fail)
    if cleanup_fails:
        mocker.patch.object(storage, "delete", side_effect=OSError("synthetic cleanup refusal"))
    with pytest.raises(RuntimeError, match="synthetic later failure"):
        call_command("sync_renditions", post_slug=post.slug)
    assert list(image.renditions.order_by("pk").values_list("pk", "file")) == before_rows
    assert Path(old.file.path).read_bytes() == old_bytes
    after_files = {p for p in Path(storage.location).rglob("*") if p.is_file()}
    if cleanup_fails:
        assert after_files > before_files
        assert "Could not remove orphaned rendition file" in caplog.text
    else:
        assert after_files == before_files


@pytest.mark.django_db
def test_publication_rendition_rollback_survives_logging_failure(disk_image, mocker):
    from cast.models.image_renditions import create_missing_renditions_for_images, logger

    class BrokenHandler(logging.Handler):
        def emit(self, record):
            raise RuntimeError("synthetic logging failure")

    storage = Rendition._meta.get_field("file").storage
    store = storage.save
    written = []

    def record_write(*args, **kwargs):
        name = store(*args, **kwargs)
        written.append(name)
        return name

    publish_failure = OSError("synthetic rendition write failure")
    save_row = Rendition.save

    def save_or_fail(rendition, *args, **kwargs):
        if len(written) == 2:
            raise publish_failure
        return save_row(rendition, *args, **kwargs)

    delete = storage.delete

    def delete_or_fail(name):
        if name == written[0]:
            raise OSError("synthetic orphan delete failure")
        delete(name)

    mocker.patch.object(storage, "save", side_effect=record_write)
    mocker.patch.object(Rendition, "save", save_or_fail)
    delete_attempt = mocker.patch.object(storage, "delete", side_effect=delete_or_fail)
    handler = BrokenHandler()
    logger.addHandler(handler)
    try:
        with pytest.raises(OSError) as exc:
            create_missing_renditions_for_images({disk_image.pk: {"width-1", "height-1"}})
    finally:
        logger.removeHandler(handler)
        handler.close()

    assert exc.value is publish_failure
    assert not disk_image.renditions.exists()
    assert [call.args[0] for call in delete_attempt.call_args_list] == written
    assert storage.exists(written[0])
    assert not storage.exists(written[1])


@pytest.mark.django_db
@pytest.mark.parametrize("rename", [False, True])
def test_unproven_storage_names_are_retained(disk_image, mocker, rename, caplog):
    from cast.models.image_renditions import create_missing_renditions_for_images

    storage = Rendition._meta.get_field("file").storage
    save = storage.save
    written = []

    def save_elsewhere(name, content, **kwargs):
        result = save("unexpected.png" if rename else name, content, **kwargs)
        written.append(result)
        return result

    mocker.patch.object(storage, "save", side_effect=save_elsewhere)
    mocker.patch.object(Rendition, "save", side_effect=RuntimeError("synthetic row failure"))
    with pytest.raises(RuntimeError, match="synthetic row failure"):
        create_missing_renditions_for_images({disk_image.pk: {"width-1"}})
    assert storage.exists(written[0]) == rename
    assert ("ownership is uncertain" in caplog.text) == rename


@pytest.mark.django_db
def test_fresh_rendition_destination_collision_does_not_touch_existing_bytes(disk_image, mocker):
    from cast.models.image_renditions import create_missing_renditions_for_images

    storage = Rendition._meta.get_field("file").storage
    mocker.patch.object(storage, "exists", return_value=True)
    save = mocker.spy(storage, "save")
    with pytest.raises(FileExistsError, match="destination already exists"):
        create_missing_renditions_for_images({disk_image.pk: {"width-1"}})
    save.assert_not_called()


@pytest.mark.django_db(transaction=True, databases={"default", "migration_other"})
@pytest.mark.parametrize("alias", ["default", "migration_other"])
@pytest.mark.parametrize("rollback", [False, True])
def test_repair_invalidates_only_after_writer_commit(disk_image, alias, rollback, mocker):
    from django.db import transaction
    from wagtail.models import Collection

    from cast.models.image_renditions import repair_missing_rendition_files

    image = disk_image
    if alias != "default":
        collection = Collection.add_root(instance=Collection(name="Synthetic other"))
        Collection.objects.using(alias).create(
            pk=collection.pk, name="Synthetic other", path=collection.path, depth=1, numchild=0
        )
        image = Image(title="Synthetic other", collection_id=collection.pk, file=disk_image.file.name)
        image.save(using=alias)
    row = image.create_rendition(Filter("width-1"))
    old_name = row.file.name
    row.file.storage.delete(old_name)
    purge = mocker.spy(Rendition, "purge_from_cache")
    with transaction.atomic(using=alias):
        with transaction.atomic(using=alias):
            repair_missing_rendition_files(image, ["width-1"])
        purge.assert_not_called()
        assert image.renditions.get(pk=row.pk).file.name != old_name
        transaction.set_rollback(rollback, using=alias)
    assert purge.call_count == (0 if rollback else 1)
    assert (image.renditions.get(pk=row.pk).file.name == old_name) == rollback


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("entry", ["command", "direct"])
def test_committed_cache_failure_keeps_repaired_bytes(post, disk_image, mocker, entry):
    from cast.models.image_renditions import RenditionCacheInvalidationError, create_missing_renditions_for_images

    row = disk_image.get_rendition("width-1")
    old_name = row.file.name
    row.file.storage.delete(old_name)
    mocker.patch(
        "cast.management.commands.sync_renditions.get_obsolete_and_missing_rendition_strings",
        return_value=(set(), {disk_image.pk: ["width-1"]}),
    )
    mocker.patch.object(Rendition, "purge_from_cache", side_effect=OSError("synthetic cache outage"))
    expected_error = CommandError if entry == "command" else RenditionCacheInvalidationError
    with pytest.raises(expected_error, match="committed.*cache purge pending"):
        if entry == "command":
            call_command("sync_renditions", post_slug=post.slug)
        else:
            create_missing_renditions_for_images({disk_image.pk: {"width-1"}}, strict_cache_invalidation=True)
    row.refresh_from_db()
    assert row.file.name != old_name
    assert row.file.storage.exists(row.file.name)


@pytest.mark.django_db(transaction=True)
def test_embedded_cache_failure_is_logged_and_keeps_later_callbacks(disk_image, mocker, caplog):
    from django.db import transaction

    from cast.models.image_renditions import create_missing_renditions_for_images

    row = disk_image.get_rendition("width-1")
    old_name = row.file.name
    row.file.storage.delete(old_name)
    mocker.patch.object(Rendition, "purge_from_cache", side_effect=OSError("synthetic cache outage"))
    later = mocker.Mock()
    with caplog.at_level("ERROR", logger="cast.models.image_renditions"):
        with transaction.atomic():
            create_missing_renditions_for_images({disk_image.pk: {"width-1"}})
            transaction.on_commit(later)
    later.assert_called_once_with()
    assert f"cache purge pending for image {disk_image.pk} (rendition {row.pk}" in caplog.text
    row.refresh_from_db()
    assert row.file.name != old_name
    assert row.file.storage.exists(row.file.name)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("entry", ["command", "direct"])
def test_unrelated_commit_callback_failure_keeps_committed_creation(post, disk_image, mocker, entry):
    from django.db import transaction

    from cast.models.image_renditions import create_missing_renditions_for_images

    mocker.patch(
        "cast.management.commands.sync_renditions.get_obsolete_and_missing_rendition_strings",
        return_value=(set(), {disk_image.pk: ["width-1"]}),
    )
    save = Rendition.save

    def fail_callback():
        raise RuntimeError("synthetic unrelated commit callback")

    def save_and_register(self, *args, **kwargs):
        result = save(self, *args, **kwargs)
        transaction.on_commit(fail_callback, using=self._state.db)
        return result

    mocker.patch.object(Rendition, "save", save_and_register)
    with pytest.raises(RuntimeError, match="synthetic unrelated commit callback"):
        if entry == "command":
            call_command("sync_renditions", post_slug=post.slug)
        else:
            create_missing_renditions_for_images({disk_image.pk: {"width-1"}})
    row = disk_image.renditions.get(filter_spec="width-1")
    assert row.file.storage.exists(row.file.name)


@pytest.mark.django_db
def test_creation_reuses_a_row_present_after_inventory(disk_image, mocker):
    from cast.models.image_renditions import create_rendition_with_receipt

    row = disk_image.get_rendition("width-1")
    generate = mocker.spy(Image, "generate_rendition_file")
    receipt = []
    assert create_rendition_with_receipt(disk_image, Filter("width-1"), receipt).pk == row.pk
    assert receipt == []
    generate.assert_not_called()
