"""Preview media use synthetic rows at equal PKs in independent databases."""

from io import BytesIO
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connections
from django.test.utils import CaptureQueriesContext
from PIL import Image as PillowImage
from wagtail.images.models import Image, Rendition
from wagtail.models import Collection

from cast.models import Audio, Gallery, Post, Video
from cast.preview_media import PreviewMedia


@pytest.mark.django_db(databases={"default", "migration_other"})
@pytest.mark.parametrize("routed", [False, True])
def test_preview_media_and_renditions_stay_on_the_post_database(settings, routed):
    # Identical source bytes deliberately collide in Wagtail's rendition cache
    # (its key includes image PK/hash/filter but not the database alias).
    data = BytesIO()
    PillowImage.new("RGB", (2, 2), "red").save(data, format="PNG")
    image_bytes = data.getvalue()
    pk = 90001
    for alias in ("default", "migration_other"):
        Collection.objects.using(alias).create(pk=pk, name="Synthetic preview", path="9999", depth=1, numchild=0)
        get_user_model().objects.using(alias).create(pk=pk, username=f"preview-{alias}")
        image = Image(
            pk=pk,
            title=alias,
            collection_id=pk,
            file=SimpleUploadedFile(f"synthetic-{alias}.png", image_bytes, content_type="image/png"),
        )
        image.save(using=alias)
        Audio.objects.using(alias).create(pk=pk, user_id=pk, collection_id=pk, title=alias)
        video = Video(pk=pk, user_id=pk, collection_id=pk, title=alias)
        video.save(using=alias, poster=False)

    assert Image.objects.get(pk=pk).file_hash == Image.objects.using("migration_other").get(pk=pk).file_hash
    blocks = [SimpleNamespace(block_type=kind, value=pk) for kind in ("image", "audio", "video")]
    blocks.append(SimpleNamespace(block_type="gallery", value={"gallery": [pk]}))
    body = [SimpleNamespace(value=blocks)]
    default_post = SimpleNamespace(_state=SimpleNamespace(db="default"), body=body)
    PreviewMedia.from_post(default_post)
    original_renditions = list(Rendition.objects.values_list("pk", "file"))
    assert original_renditions
    default_image = Image.objects.get(pk=pk)
    for rendition in Rendition.objects.filter(image_id=pk):
        default_image.get_rendition(rendition.filter_spec)  # prewarm the shared cache
    assert not Rendition.objects.using("migration_other").exists()

    class PreviewRouter:
        def db_for_read(self, model, **hints):
            if model is SimpleNamespace:
                return "migration_other"

    if routed:
        settings.DATABASE_ROUTERS = [PreviewRouter()]
    post = SimpleNamespace(_state=SimpleNamespace(db=None if routed else "migration_other"), body=body)
    with CaptureQueriesContext(connections["default"]) as default_queries:
        media = PreviewMedia.from_post(post)
    assert list(default_queries) == []
    for objects in (media.images, media.audios, media.videos):
        assert objects[pk].title == "migration_other"
        assert objects[pk]._state.db == "migration_other"
    assert media.renditions[pk]
    assert all(rendition._state.db == "migration_other" for rendition in media.renditions[pk])
    assert Rendition.objects.using("migration_other").count() == len(original_renditions)
    assert list(Rendition.objects.values_list("pk", "file")) == original_renditions
    for rendition in Rendition.objects.filter(image_id=pk):
        cached = default_image.get_rendition(rendition.filter_spec)
        assert cached._state.db == "default"
        assert cached.file.name == rendition.file.name
    assert not Gallery.objects.using("migration_other").exists()
    for name in ("images", "audios", "videos", "galleries"):
        assert not getattr(Post, name).through.objects.using("migration_other").exists()
