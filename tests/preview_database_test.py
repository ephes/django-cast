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


@pytest.mark.django_db(databases={"default", "migration_other"})
@pytest.mark.parametrize("alias", ["default", "migration_other"])
def test_preview_uses_configured_image_and_rendition_models(settings, alias):
    from cast.models.image_renditions import get_all_filterstrings
    from tests.preview_image_app.models import PreviewImage, PreviewRendition

    settings.WAGTAILIMAGES_IMAGE_MODEL = "preview_image_app.PreviewImage"
    data = BytesIO()
    PillowImage.new("RGB", (2, 2), "blue").save(data, format="PNG")
    pk = 91001
    # Equal IDs in the concrete and configured image tables make accidental
    # hydration observable rather than silently returning no images.
    for db in {"default", alias}:
        Collection.objects.using(db).create(pk=pk, name="Synthetic custom", path="9998", depth=1, numchild=0)
        for model in (Image, PreviewImage):
            instance = model(
                pk=pk,
                title=f"{db}-{model.__name__}",
                collection_id=pk,
                file=SimpleUploadedFile("synthetic.png", data.getvalue(), content_type="image/png"),
            )
            instance.save(using=db)
    image = PreviewImage.objects.using(alias).get(pk=pk)
    required = set(get_all_filterstrings([("regular", image), ("gallery", image)]))
    # A concrete rendition with an expected spec must not satisfy custom inventory.
    spec = next(iter(required))[1]
    Rendition.objects.using(alias).create(image_id=pk, filter_spec=spec, width=1, height=1, file="concrete.png")
    concrete_before = list(Rendition.objects.using(alias).values_list("pk", "file"))
    blocks = [
        SimpleNamespace(block_type="image", value=pk),
        SimpleNamespace(block_type="gallery", value={"gallery": [pk]}),
    ]
    post = SimpleNamespace(_state=SimpleNamespace(db=alias), body=[SimpleNamespace(value=blocks)])
    with CaptureQueriesContext(connections["migration_other" if alias == "default" else "default"]) as other_queries:
        first = PreviewMedia.from_post(post)
        count = PreviewRendition.objects.using(alias).count()
        second = PreviewMedia.from_post(post)
    assert list(other_queries) == []
    for media in (first, second):
        assert type(media.images[pk]) is PreviewImage
        assert media.images[pk].title == f"{alias}-PreviewImage"
        assert {(r.image_id, r.filter_spec) for r in media.renditions[pk]} == required
        assert all(
            type(r) is PreviewRendition and r._state.db == alias and r.file.storage.exists(r.file.name)
            for r in media.renditions[pk]
        )
    assert PreviewRendition.objects.using(alias).count() == count == len(required)
    assert list(Rendition.objects.using(alias).values_list("pk", "file")) == concrete_before
    assert not Gallery.objects.using(alias).exists()
