"""Synthetic relation generations and concurrent canonical gallery creation."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import close_old_connections, connection
from django.db.models import QuerySet
from django.db.models.signals import m2m_changed

from cast.devdata import create_image
from cast.models import Audio, Gallery, get_or_create_gallery
from cast.post_media import synchronize_post_media


@pytest.mark.django_db(transaction=True)
def test_media_relation_failure_rolls_back_all_updates(pg_editor_actors, post, monkeypatch):
    images = [create_image(), create_image()]
    audios = [Audio.objects.create(user=post.owner, collection=images[0].collection) for _ in range(2)]
    post.images.add(images[0])
    post.audios.add(audios[0])
    wanted = {"image": {images[1].pk}, "audio": {audios[1].pk}}
    monkeypatch.setattr("cast.post_media.media_ids_from_body", lambda *args: wanted)
    updates = []

    def fail_second(sender, instance, action, **kwargs):
        if instance is post and action == "post_add":
            updates.append(sender)
            if len(updates) == 2:
                raise RuntimeError("second relation failed")

    m2m_changed.connect(fail_second, weak=False)
    try:
        with pytest.raises(RuntimeError, match="second relation"):
            synchronize_post_media(post)
    finally:
        m2m_changed.disconnect(fail_second)
    assert len(updates) == 2  # the failure actually followed a successful write
    assert set(post.images.values_list("pk", flat=True)) == {images[0].pk}
    assert set(post.audios.values_list("pk", flat=True)) == {audios[0].pk}
    synchronize_post_media(post)
    assert set(post.images.values_list("pk", flat=True)) == wanted["image"]
    assert set(post.audios.values_list("pk", flat=True)) == wanted["audio"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(connection.vendor != "postgresql", reason="Requires independent row-lock transactions")
def test_concurrent_gallery_creation_returns_one_effective_set(pg_editor_actors, monkeypatch):
    images = [create_image(), create_image()]
    ids = [image.pk for image in images]
    first_lookup = threading.Event()
    second_boundary = threading.Event()
    release = threading.Event()
    role = threading.local()
    original_first = QuerySet.first

    def observe_first(queryset):
        result = original_first(queryset)
        if queryset.model is Gallery:
            if role.index == 0:
                first_lookup.set()
                assert release.wait(10)
            else:
                second_boundary.set()
        return result

    monkeypatch.setattr(QuerySet, "first", observe_first)

    def create(index):
        role.index = index
        close_old_connections()
        try:

            def observe_lock(execute, sql, params, many, context):
                if index and ("FOR UPDATE" in sql or "FOR NO KEY UPDATE" in sql) and '"wagtailimages_image"' in sql:
                    second_boundary.set()
                return execute(sql, params, many, context)

            with connection.execute_wrapper(observe_lock):
                requested = ids if not index else [999999, *reversed(ids), ids[0]]
                return get_or_create_gallery(requested).pk
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(create, 0)
        try:
            assert first_lookup.wait(10)
            second = pool.submit(create, 1)
            # Fixed code attempts the shared image lock; old code completes
            # the second empty signature lookup before either gallery exists.
            assert second_boundary.wait(10)
        finally:
            release.set()
        gallery_ids = [first.result(timeout=20), second.result(timeout=20)]
    assert gallery_ids[0] == gallery_ids[1]
    assert Gallery.objects.filter(signature=Gallery.build_signature(ids)).count() == 1
    assert Gallery.objects.get(pk=gallery_ids[0]).image_ids == set(ids)


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(connection.vendor != "postgresql", reason="Requires independent row-lock transactions")
def test_publication_locks_all_gallery_sets_in_one_order(pg_editor_actors, monkeypatch):
    from types import SimpleNamespace

    from django.db import transaction

    from cast.post_media import media_ids_from_body

    ids = [create_image().pk, create_image().pk]
    first_lookup = threading.Event()
    second_boundary = threading.Event()
    release = threading.Event()
    role = threading.local()
    original_first = QuerySet.first

    def observe_first(queryset):
        result = original_first(queryset)
        if queryset.model is Gallery:
            role.lookups += 1
            if role.index == 0 and role.lookups == 1:
                first_lookup.set()
                assert release.wait(10)
            elif role.index:
                second_boundary.set()
        return result

    monkeypatch.setattr(QuerySet, "first", observe_first)

    def publish(index):
        role.index = index
        role.lookups = 0
        close_old_connections()
        ordered = ids if not index else list(reversed(ids))
        body = [
            SimpleNamespace(
                value=[SimpleNamespace(block_type="gallery", value={"gallery": [image_id]}) for image_id in ordered]
            )
        ]
        try:

            def observe_lock(execute, sql, params, many, context):
                if index and "FOR " in sql and '"wagtailimages_image"' in sql and len(params) == 2:
                    second_boundary.set()  # the complete union is about to be locked
                return execute(sql, params, many, context)

            with connection.execute_wrapper(observe_lock), transaction.atomic():
                return media_ids_from_body(SimpleNamespace(media_model_lookup={"gallery": Gallery}), body)["gallery"]
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(publish, 0)
        try:
            assert first_lookup.wait(10)
            second = pool.submit(publish, 1)
            assert second_boundary.wait(10)
        finally:
            release.set()
        results = [first.result(timeout=20), second.result(timeout=20)]
    assert results[0] == results[1]
    assert Gallery.objects.count() == 2
