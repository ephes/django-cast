"""Gallery mutations must stay on the relation's database, even with colliding PKs."""

from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connections
from django.test.utils import CaptureQueriesContext
from PIL import Image as PillowImage
from wagtail.images.models import Image
from wagtail.models import Collection

from cast.models import Gallery


@pytest.mark.django_db(databases={"default", "migration_other"})
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("action", ["add", "remove", "clear", "delete"])
def test_gallery_mutation_uses_its_database(reverse, action):
    data = BytesIO()
    PillowImage.new("RGB", (2, 2), "red").save(data, format="PNG")
    for alias in ("default", "migration_other"):
        Collection.objects.using(alias).create(pk=90001, name="Synthetic", path="9999", depth=1, numchild=0)
        for pk in (90001, 90002):
            image = Image(
                pk=pk,
                title=alias,
                collection_id=90001,
                file=SimpleUploadedFile(f"synthetic-{alias}-{pk}.png", data.getvalue()),
            )
            image.save(using=alias)
        gallery = Gallery.objects.using(alias).create(pk=90001)
        gallery.images.add(90001)
        if action != "add":
            gallery.images.add(90002)
    original_default = Gallery.objects.get(pk=90001).signature
    alias = "migration_other"
    gallery = Gallery.objects.using(alias).get(pk=90001)
    image = Image.objects.using(alias).get(pk=90002)
    manager, target = (image.gallery_set, gallery) if reverse else (gallery.images, image)
    with CaptureQueriesContext(connections["default"]) as default_queries:
        if action == "delete":
            image.delete(using=alias)
        elif action == "clear":
            manager.clear()
        else:
            getattr(manager, action)(target)
    # Wagtail search signals have their own routing; only gallery queries are in scope.
    assert not any("cast_gallery" in query["sql"] for query in default_queries)
    gallery.refresh_from_db(using=alias)
    assert gallery.signature == Gallery.build_signature(gallery.images.using(alias).values_list("pk", flat=True))
    assert Gallery.objects.get(pk=90001).signature == original_default
