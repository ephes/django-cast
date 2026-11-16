"""Media indexes use the owning database and current persisted body."""

from types import SimpleNamespace

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import connections
from django.test.utils import CaptureQueriesContext
from wagtail.images.models import Image
from wagtail.models import Collection, Locale, Page

from cast.models import Gallery, Post
from cast.post_media import media_ids_from_body, synchronize_post_media


@pytest.mark.django_db(databases={"default", "migration_other"})
def test_post_media_uses_source_database(post, image, settings):
    alias = "migration_other"
    Collection.objects.using(alias).create(pk=image.collection_id, name="Synthetic", path="9999", depth=1, numchild=0)
    secondary_image = Image(pk=image.pk, collection_id=image.collection_id, title="Secondary", file=image.file.name)
    secondary_image.save(using=alias)
    locale = Locale.objects.get(pk=post.locale_id)
    locale.save_base(raw=True, using=alias, force_insert=True)
    page = Page.objects.get(pk=post.pk)
    page.content_type_id = ContentType.objects.db_manager(alias).get_for_model(Post).pk
    page.owner = None
    page.save_base(raw=True, using=alias, force_insert=True)
    post.save_base(raw=True, using=alias, force_insert=True)
    post._state.db = "default"
    body = [
        {
            "type": "overview",
            "value": [
                {"type": "image", "value": image.pk},
                {"type": "gallery", "value": {"gallery": [{"type": "item", "value": image.pk}]}},
            ],
        }
    ]
    Post.objects.using(alias).filter(pk=post.pk).update(body=body)
    secondary = Post.objects.using(alias).get(pk=post.pk)

    class GalleryRouter:
        def db_for_write(self, model, **hints):
            if model is Gallery:
                return "default"

    settings.DATABASE_ROUTERS = [GalleryRouter()]
    # Integer chooser values also need the explicit owning alias.
    numeric_body = [SimpleNamespace(value=[SimpleNamespace(block_type="image", value=image.pk)])]
    with CaptureQueriesContext(connections["default"]) as queries:
        assert media_ids_from_body(secondary, numeric_body) == {"image": {image.pk}}
        synchronize_post_media(secondary)
    assert not any('"wagtailimages_image"' in q["sql"] or '"cast_gallery"' in q["sql"] for q in queries)
    assert set(secondary.images.using(alias).values_list("pk", flat=True)) == {image.pk}
    assert secondary.galleries.using(alias).get().image_ids == {image.pk}
    assert not post.images.exists()
    assert not Gallery.objects.exists()


@pytest.mark.django_db
def test_delayed_media_preparation_uses_current_body(post, image):
    stale = Post.objects.get(pk=post.pk)
    stale.body = [
        {
            "type": "overview",
            "value": [{"type": "gallery", "value": {"gallery": [{"type": "item", "value": image.pk}]}}],
        }
    ]
    # The persisted generation has already advanced to an empty body.
    Post.objects.filter(pk=post.pk).update(body=[])
    synchronize_post_media(stale)
    assert not post.galleries.exists()
    assert not Gallery.objects.exists()  # stale work must not even create a gallery
    assert stale.body  # request-local draft data remains intact


@pytest.mark.django_db
def test_cached_media_snapshot_cannot_hide_stored_relationships(post_with_image):
    post = post_with_image
    image_id = post.images.get().pk
    assert post.media_ids_from_db == {"image": {image_id}, "audio": set(), "video": set(), "gallery": set()}
    post._media_lookup = {}  # request-local rendering snapshot predates the relationship
    Post.objects.filter(pk=post.pk).update(body=[])
    synchronize_post_media(post)
    assert not post.images.exists()


@pytest.mark.django_db
def test_synchronization_keeps_subclass_media_lookups(episode, monkeypatch):
    from cast.models import Episode, Post
    from cast.post_media import synchronize_post_media

    seen = []

    def recording(name):
        base = getattr(Post, name)

        def lookup(self):
            seen.append((name, type(self)))
            return base.fget(self)

        return property(lookup)

    monkeypatch.setattr(Episode, "media_model_lookup", recording("media_model_lookup"))
    monkeypatch.setattr(Episode, "media_attr_lookup", recording("media_attr_lookup"))
    synchronize_post_media(episode)
    assert ("media_attr_lookup", Episode) in seen
    assert ("media_model_lookup", Episode) in seen
