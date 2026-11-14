"""Direct generation preserves database identity and repairs lost objects."""

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import connections
from django.test.utils import CaptureQueriesContext
from PIL import Image as PillowImage
from wagtail.images.models import Image, Rendition
from wagtail.models import Collection

from cast.models import Gallery
from cast.models.image_renditions import (
    create_missing_renditions_for_posts,
    get_all_filterstrings,
    get_obsolete_and_missing_rendition_strings,
)


@pytest.mark.django_db(databases={"default", "migration_other"})
@pytest.mark.parametrize("entry", ["gallery", "posts"])
def test_direct_generation_keeps_colliding_images_on_source_database(entry, tmp_path, monkeypatch):
    data = BytesIO()
    PillowImage.new("RGB", (2, 2), "red").save(data, "PNG")
    storage = FileSystemStorage(location=tmp_path)
    monkeypatch.setattr(Image._meta.get_field("file"), "storage", storage)
    monkeypatch.setattr(Rendition._meta.get_field("file"), "storage", storage)
    for alias in ("default", "migration_other"):
        Collection.objects.using(alias).create(pk=90001, name="Synthetic", path="9999", depth=1, numchild=0)
        image = Image(
            pk=90001, title=alias, collection_id=90001, file=SimpleUploadedFile(f"{alias}.png", data.getvalue())
        )
        image.save(using=alias)
    gallery = Gallery.objects.using("migration_other").create()
    gallery.images.add(90001)
    image = Image.objects.using("migration_other").get(pk=90001)
    default_image = Image.objects.get(pk=90001)
    for _, spec in get_all_filterstrings([("gallery", default_image)]):
        default_image.get_rendition(spec)  # warm colliding shared cache keys
    before = list(Rendition.objects.values_list("pk", "file"))
    with CaptureQueriesContext(connections["default"]) as queries:
        if entry == "gallery":
            gallery.create_renditions()
        else:
            post = SimpleNamespace(get_all_images=lambda: iter([("gallery", image)]))
            create_missing_renditions_for_posts(iter([post]))
    assert not queries
    assert list(Rendition.objects.values_list("pk", "file")) == before
    renditions = list(Rendition.objects.using("migration_other").all())
    assert renditions
    assert all(r.file.storage.exists(r.file.name) and "migration_other" in r.file.name for r in renditions)


@pytest.mark.django_db
@pytest.mark.parametrize("fail", [False, True])
def test_sync_repairs_existing_row_with_missing_file(
    post, disk_image, mocker, fail, django_capture_on_commit_callbacks
):
    image = disk_image
    post.images.add(image)
    # Restrict the required policy to one spec and one sRGB counterpart.
    mocker.patch("cast.models.image_renditions.get_all_filterstrings", return_value=[(image.pk, "width-1|srgb")])
    mocker.patch(
        "cast.models.image_renditions.get_gallery_thumbnail_srgb_counterpart_filterstrings",
        return_value=[(image.pk, "width-1")],
    )
    # Make the post's image a gallery image so the counterpart is owned.
    mocker.patch("cast.models.Post.get_all_images_from_queryset", return_value=[("gallery", image)])
    missing = image.get_rendition("width-1|srgb")
    counterpart = image.get_rendition("width-1")
    image.file.storage.delete(missing.file.name)
    original_generate = Image.generate_rendition_file
    if fail:
        mocker.patch.object(Image, "generate_rendition_file", side_effect=OSError("synthetic write refusal"))
        with pytest.raises(OSError, match="synthetic"):
            call_command("sync_renditions", post_slug=post.slug)
        assert Rendition.objects.filter(pk=counterpart.pk).exists()
        assert counterpart.file.storage.exists(counterpart.file.name)
        assert Rendition.objects.filter(pk=missing.pk).exists()
        mocker.patch.object(Image, "generate_rendition_file", original_generate)
    with django_capture_on_commit_callbacks(execute=True):
        call_command("sync_renditions", post_slug=post.slug)
    repaired = image.renditions.get(filter_spec="width-1|srgb")
    assert repaired.pk == missing.pk
    assert repaired.file.storage.exists(repaired.file.name)
    assert not Rendition.objects.filter(pk=counterpart.pk).exists()


@pytest.mark.django_db
def test_planning_checks_each_required_storage_key_once(disk_image, mocker):
    image = disk_image
    rendition = image.get_rendition("width-1")
    mocker.patch("cast.models.image_renditions.get_all_filterstrings", return_value=[(image.pk, "width-1")])
    exists = mocker.spy(rendition.file.storage, "exists")
    assert get_obsolete_and_missing_rendition_strings([("regular", image)] * 20) == (set(), {})
    assert exists.call_count == 1


@pytest.mark.django_db
def test_inventory_refuses_mixed_database_identities(disk_image):
    other = Image(pk=disk_image.pk)
    other._state.db = "migration_other"
    with pytest.raises(ValueError, match="one database"):
        get_obsolete_and_missing_rendition_strings([("regular", disk_image), ("regular", other)])


@pytest.mark.django_db
def test_planning_reuses_existence_for_shared_keys_and_handles_empty_names(disk_image, mocker):
    image = disk_image
    first = image.get_rendition("width-1")
    second = image.get_rendition("height-1")
    second.file.name = first.file.name
    second.save(update_fields=["file"])
    empty = image.get_rendition("fill-1x1")
    empty.file.name = ""
    empty.save(update_fields=["file"])
    mocker.patch(
        "cast.models.image_renditions.get_all_filterstrings",
        return_value=[(image.pk, "width-1"), (image.pk, "height-1"), (image.pk, "fill-1x1")],
    )
    exists = mocker.spy(first.file.storage, "exists")
    assert get_obsolete_and_missing_rendition_strings([("regular", image)]) == (set(), {image.pk: {"fill-1x1"}})
    assert exists.call_count == 1


@pytest.mark.django_db
@pytest.mark.parametrize("failure", ["database", "storage-verification"])
def test_failed_repair_keeps_row_and_cleans_attempt_file(disk_image, mocker, failure):
    from django.db import transaction

    from cast.models.image_renditions import repair_missing_rendition_files

    image = disk_image
    row = image.get_rendition("width-1")
    name, pk = row.file.name, row.pk
    row.file.storage.delete(name)
    if failure == "database":
        mocker.patch.object(Rendition, "save", side_effect=RuntimeError("synthetic publication failure"))
    else:
        mocker.patch.object(row.file.storage, "exists", return_value=False)
    with pytest.raises((RuntimeError, OSError)), transaction.atomic():
        repair_missing_rendition_files(image, ["width-1"])
    assert Rendition.objects.filter(pk=pk, file=name).exists()
    assert not Path(row.file.storage.path(name)).exists()


@pytest.mark.django_db
def test_direct_creation_verifies_storage_and_does_not_rewrite_usable_rows(disk_image, mocker):
    from cast.models.image_renditions import create_missing_renditions_for_images, repair_missing_rendition_files

    image = disk_image
    row = image.get_rendition("width-1")
    save = mocker.spy(Rendition, "save")
    repair_missing_rendition_files(image, ["width-1"])
    save.assert_not_called()
    mocker.patch.object(Image, "create_rendition", return_value=row)
    mocker.patch.object(row.file.storage, "exists", side_effect=[True, False])
    with pytest.raises(OSError, match="not saved"):
        create_missing_renditions_for_images({image.pk: {"width-1"}})
