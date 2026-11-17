"""Create must resolve media authority after waiting for the parent writer."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import close_old_connections, connection, transaction
from django.urls import reverse
from rest_framework.test import APIClient
from wagtail.models import Collection, GroupCollectionPermission, Page, Revision

from cast.api.editor.views import PostEditorMixin
from cast.content.media_refs import get_choosable_image
from cast.models import Post
from tests.api.editor_posts_helpers import (
    grant_collection_permission,
    grant_wagtail_admin_access,
    page_permission_user,
)


@pytest.fixture
def create_media_case(pg_editor_actors, image, audio, video):
    _, parent = pg_editor_actors
    actor = page_permission_user(codenames=("add_page",))
    grant_wagtail_admin_access(actor)
    collection = Collection.get_first_root_node().add_child(name="Synthetic allowed media")
    forbidden = Collection.get_first_root_node().add_child(name="Synthetic unavailable media")
    for obj in (image, audio, video):
        obj.collection = collection
        obj.save(update_fields=["collection"])
    for app_label, codename in (("wagtailimages", "choose_image"), ("cast", "choose_audio"), ("cast", "choose_video")):
        grant_collection_permission(actor, collection, app_label=app_label, codename=codename)
    return actor, parent, {"image": image, "audio": audio, "video": video}, forbidden


def media_payload(parent, objects, kind):
    payload = {
        "parent": {"id": parent.pk},
        "title": "Synthetic media create",
        "overview": [],
        "tags": ["synthetic-media-tag"],
    }
    if kind == "cover":
        payload["cover_image"] = {"id": objects["image"].pk}
    else:
        ref = {"id": objects["image" if kind == "gallery" else kind].pk}
        payload["detail"] = [{"type": kind, "value": [ref] if kind == "gallery" else ref}]
    return payload


def assert_refused(response, before, kind):
    assert response.status_code == 400, response.content
    path = "cover_image.id" if kind == "cover" else "detail.0.value.0.id" if kind == "gallery" else "detail.0.value.id"
    assert path in response.json()["errors"], response.json()
    assert response.json()["errors"][path][0]["code"] == "not_found"
    assert (Page.objects.count(), Post.objects.count(), Revision.objects.count()) == before
    from taggit.models import Tag

    assert not Tag.objects.filter(name="synthetic-media-tag").exists()


@pytest.mark.parametrize("kind", ["cover", "image", "gallery", "audio", "video"])
@pytest.mark.parametrize("change", ["grant", "collection", "superuser"])
def test_create_rechecks_media_after_parent_lock(create_media_case, api_client, monkeypatch, kind, change):
    actor, parent, objects, forbidden = create_media_case
    if change == "superuser":
        actor.is_superuser = True
        actor.save()
    # Prime Wagtail's request-user permission cache before the lock wait.
    assert get_choosable_image(objects["image"].pk, actor) is not None
    original = PostEditorMixin._lock_parent_for_slug_check

    def before_lock(self, selected, *, noun):
        if change == "collection":
            for obj in objects.values():
                type(obj).objects.filter(pk=obj.pk).update(collection=forbidden)
        else:
            GroupCollectionPermission.objects.filter(group__user=actor).delete()
            get_user_model().objects.filter(pk=actor.pk).update(is_superuser=False)
        return original(self, selected, noun=noun)

    monkeypatch.setattr(PostEditorMixin, "_lock_parent_for_slug_check", before_lock)
    api_client.force_authenticate(user=actor)
    before = Page.objects.count(), Post.objects.count(), Revision.objects.count()
    response = api_client.post(
        reverse("cast:api:editor_post_create"), media_payload(parent, objects, kind), format="json"
    )
    assert_refused(response, before, kind)
    # The refused transaction also rolls back the interleaved local changes.
    # Reuse its slug with a fresh authorized request to prove recovery.
    monkeypatch.setattr(PostEditorMixin, "_lock_parent_for_slug_check", original)
    api_client.force_authenticate(user=get_user_model().objects.get(pk=actor.pk))
    retry = api_client.post(
        reverse("cast:api:editor_post_create"), media_payload(parent, objects, kind), format="json"
    )
    assert retry.status_code == 201, retry.content
    assert (Page.objects.count(), Post.objects.count(), Revision.objects.count()) == tuple(n + 1 for n in before)


@pytest.mark.parametrize("kind", ["cover", "image", "gallery", "audio", "video"])
def test_postgres_create_rechecks_media_after_real_parent_wait(create_media_case, monkeypatch, kind):
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL independent committed connections and parent-row wait")
    actor, parent, objects, _ = create_media_case
    payload = media_payload(parent, objects, kind)
    original = PostEditorMixin._lock_parent_for_slug_check
    attempting = threading.Event()
    writer_pid = []

    def at_lock(self, selected, *, noun):
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            writer_pid.append(cursor.fetchone()[0])
            cursor.execute("SET LOCAL lock_timeout = '10s'")
        attempting.set()
        return original(self, selected, noun=noun)

    def create():
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(user=get_user_model().objects.get(pk=actor.pk))
            return client.post(reverse("cast:api:editor_post_create"), payload, format="json")
        finally:
            close_old_connections()

    before = Page.objects.count(), Post.objects.count(), Revision.objects.count()
    monkeypatch.setattr(PostEditorMixin, "_lock_parent_for_slug_check", at_lock)
    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            Page.objects.select_for_update().get(pk=parent.pk)
            future = executor.submit(create)
            assert attempting.wait(10)
            deadline = time.monotonic() + 5
            while True:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid = %s AND NOT granted)", [writer_pid[0]]
                    )
                    waiting = cursor.fetchone()[0]
                if waiting:
                    break
                assert time.monotonic() < deadline, "Create never waited on the parent writer"
                time.sleep(0.01)
            # Commit the withdrawal before releasing the parent's writer lock.
            # Drop the grant groups too, so the recovery below can re-grant them.
            Group.objects.filter(user=actor, collection_permissions__isnull=False).delete()
        response = future.result(timeout=15)
    assert_refused(response, before, kind)

    # A new authorized request must recover normally, including its first revision.
    for app_label, codename in (("wagtailimages", "choose_image"), ("cast", "choose_audio"), ("cast", "choose_video")):
        grant_collection_permission(actor, objects["image"].collection, app_label=app_label, codename=codename)
    monkeypatch.setattr(PostEditorMixin, "_lock_parent_for_slug_check", original)
    response = create()
    assert response.status_code == 201, response.content
    assert (Page.objects.count(), Post.objects.count(), Revision.objects.count()) == tuple(n + 1 for n in before)
