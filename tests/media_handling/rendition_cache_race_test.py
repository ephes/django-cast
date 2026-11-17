"""A reader may refill an old row until the writer actually commits."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import close_old_connections, connection, transaction
from wagtail.images.models import Image, Rendition

from cast.models.image_renditions import repair_missing_rendition_files


@pytest.mark.skipif(connection.vendor != "postgresql", reason="Requires independent PostgreSQL connections")
@pytest.mark.django_db(transaction=True)
def test_reader_refill_before_commit_is_invalidated(disk_image):
    image = disk_image
    old = image.get_rendition("width-1")
    old.file.storage.delete(old.file.name)
    old.purge_from_cache()
    ready, release = threading.Event(), threading.Event()

    def repair():
        close_old_connections()
        try:
            with transaction.atomic():
                writer_image = Image.objects.get(pk=image.pk)
                repair_missing_rendition_files(writer_image, ["width-1"])
                replacement = writer_image.renditions.get(pk=old.pk).file.name
                ready.set()
                assert release.wait(10)
            return replacement
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=1) as pool:
        writer = pool.submit(repair)
        try:
            assert ready.wait(10)
            # This independent connection still sees the old committed row and
            # fills the shared cache after any premature purge has already run.
            reader = Image.objects.get(pk=image.pk)
            assert reader.get_rendition("width-1").file.name == old.file.name
        finally:
            release.set()
        replacement = writer.result(timeout=20)
    assert replacement != old.file.name
    current = Image.objects.get(pk=image.pk).get_rendition("width-1")
    assert current.file.name == replacement
    assert current.file.storage.exists(current.file.name)
    assert Rendition.objects.get(pk=old.pk).file.name == replacement
