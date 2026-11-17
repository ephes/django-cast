"""Admin media deletion only removes the generation the editor reviewed."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.core.files.base import ContentFile
from django.db import close_old_connections, connection, transaction
from django.test import Client
from django.utils import timezone
from wagtail.models import Collection, GroupCollectionPermission

from cast.models import Audio, Transcript, Video
from cast.views import media as media_views
from tests.admin_media_permissions_test import (
    MEDIA_ADMIN_CASES,
    MediaAdminCase,
    create_limited_admin,
    grant_audio_choose,
    media_admin_codenames,
    media_admin_url,
)

CASE_IDS = [case.namespace for case in MEDIA_ADMIN_CASES]


def replace_generation(item) -> str:
    """Replace the reviewed media generation like another editor would, keeping the row id."""
    if isinstance(item, Audio):
        item.title = "Replacement B"
        item.m4a.save("replacement-b.m4a", ContentFile(b"B"), save=False)
        item.save(duration=False, cache_file_sizes=False)
        return item.m4a.name
    if isinstance(item, Video):
        item.title = "Replacement B"
        item.original.save("replacement-b.mp4", ContentFile(b"B"), save=False)
        item.save(poster=False)
        return item.original.name
    assert isinstance(item, Transcript)
    item.vtt.save("replacement-b.vtt", ContentFile(b"WEBVTT\n"), save=False)
    item.save()
    return item.vtt.name


def stored_name(item) -> str:
    field = {Audio: "m4a", Video: "original", Transcript: "vtt"}[type(item)]
    return getattr(item, field).name


def get_confirmation(client, case: MediaAdminCase, item) -> str:
    response = client.get(media_admin_url(case, "delete", item))
    assert response.status_code == 200
    token = response.context["delete_confirmation"]
    assert f'name="confirmation" value="{token}"' in response.content.decode()
    return token


@pytest.fixture
def media_owner(django_user_model):
    return django_user_model.objects.create_user(username="media-owner", password="password")


@pytest.fixture
def media_root_collection(db):
    root = Collection.get_first_root_node()
    assert root is not None
    return root


@pytest.mark.django_db
@pytest.mark.parametrize("case", MEDIA_ADMIN_CASES, ids=CASE_IDS)
def test_stale_confirmation_refuses_replaced_generation(admin_client, admin_user, media_root_collection, case):
    item = case.create_item(user=admin_user, collection=media_root_collection, title="Reviewed A")
    stale_token = get_confirmation(admin_client, case, item)

    replacement_name = replace_generation(case.model.objects.get(pk=item.pk))
    response = admin_client.post(media_admin_url(case, "delete", item), {"confirmation": stale_token})

    assert response.status_code == 409
    current = case.model.objects.get(pk=item.pk)
    assert stored_name(current) == replacement_name
    storage = getattr(current, {Audio: "m4a", Video: "original", Transcript: "vtt"}[case.model]).storage
    assert storage.exists(replacement_name)
    # The refusal shows the current generation with a fresh confirmation for it.
    fresh_token = response.context["delete_confirmation"]
    assert fresh_token != stale_token
    assert response.context[case.context_key[:-1]].pk == item.pk
    messages = [str(message) for message in response.context["messages"]]
    assert any("changed since" in message for message in messages)

    response = admin_client.post(media_admin_url(case, "delete", item), {"confirmation": fresh_token})

    assert response.status_code == 302
    assert not case.model.objects.filter(pk=item.pk).exists()
    # Replaying the consumed confirmation finds no row.
    replay = admin_client.post(media_admin_url(case, "delete", item), {"confirmation": fresh_token})
    assert replay.status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize("case", MEDIA_ADMIN_CASES, ids=CASE_IDS)
@pytest.mark.parametrize("token", ["", "forged", None])
def test_missing_or_invalid_confirmation_refuses_deletion(
    admin_client, admin_user, media_root_collection, case, token
):
    item = case.create_item(user=admin_user, collection=media_root_collection, title="Reviewed A")
    data = {"delete": "yes"} if token is None else {"confirmation": token}

    response = admin_client.post(media_admin_url(case, "delete", item), data)

    assert response.status_code == 409
    assert case.model.objects.filter(pk=item.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("case", MEDIA_ADMIN_CASES, ids=CASE_IDS)
def test_expired_confirmation_refuses_deletion(admin_client, admin_user, media_root_collection, case, monkeypatch):
    item = case.create_item(user=admin_user, collection=media_root_collection, title="Reviewed A")
    token = get_confirmation(admin_client, case, item)
    monkeypatch.setattr(media_views, "DELETE_CONFIRMATION_MAX_AGE", -1)

    response = admin_client.post(media_admin_url(case, "delete", item), {"confirmation": token})

    assert response.status_code == 409
    assert case.model.objects.filter(pk=item.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("case", MEDIA_ADMIN_CASES, ids=CASE_IDS)
def test_confirmation_is_bound_to_reviewed_object(admin_client, admin_user, media_root_collection, case):
    reviewed = case.create_item(user=admin_user, collection=media_root_collection, title="Reviewed A")
    other = case.create_item(user=admin_user, collection=media_root_collection, title="Other C")
    token = get_confirmation(admin_client, case, reviewed)

    response = admin_client.post(media_admin_url(case, "delete", other), {"confirmation": token})

    assert response.status_code == 409
    assert case.model.objects.filter(pk=other.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("case", MEDIA_ADMIN_CASES, ids=CASE_IDS)
def test_lost_delete_permission_refuses_reviewed_confirmation(client, case, media_root_collection, media_owner):
    permitted = media_root_collection.add_child(instance=Collection(name="Permitted media"))
    user = create_limited_admin(model=case.model, collection=permitted, codenames=media_admin_codenames(case))
    if case.model is Transcript:
        grant_audio_choose(user, permitted)
    # Owned by someone else, so only the collection delete permission authorizes the deletion.
    item = case.create_item(user=media_owner, collection=permitted, title="Reviewed A")
    assert client.login(username=user.username, password="password")
    token = get_confirmation(client, case, item)

    # Wagtail's ownership policy also derives delete access from the change permission.
    model_name = case.model._meta.model_name
    GroupCollectionPermission.objects.filter(
        group__user=user, permission__codename__in=[f"change_{model_name}", f"delete_{model_name}"]
    ).delete()
    response = client.post(media_admin_url(case, "delete", item), {"confirmation": token})

    assert response.status_code == 404
    assert case.model.objects.filter(pk=item.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("case", MEDIA_ADMIN_CASES, ids=CASE_IDS)
def test_row_removed_before_claim_returns_not_found(admin_client, admin_user, case, monkeypatch):
    """The current row is reloaded through the delete permission after the write claim."""
    root = Collection.get_first_root_node()
    item = case.create_item(user=admin_user, collection=root, title="Reviewed A")
    token = get_confirmation(admin_client, case, item)
    original_claim = media_views.claim_row_write

    def claim_after_concurrent_delete(model, pk, *, using):
        # Another session removed the row after this request's first lookup.
        model.objects.filter(pk=pk).delete()
        original_claim(model, pk, using=using)

    monkeypatch.setattr(media_views, "claim_row_write", claim_after_concurrent_delete)

    response = admin_client.post(media_admin_url(case, "delete", item), {"confirmation": token})

    assert response.status_code == 404


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("case", MEDIA_ADMIN_CASES, ids=CASE_IDS)
def test_confirmation_waits_for_concurrent_writer_and_refuses_its_generation(django_user_model, case):
    """A writer's uncommitted replacement must not be deleted on the strength of the old review.

    The delete request runs on its own committed connection. SQLite exercises the
    database writer claim taken before the current generation is read; PostgreSQL
    exercises the row lock.
    """
    # An earlier transactional test may have flushed the migrated root collection.
    collection = Collection.get_first_root_node() or Collection.add_root(instance=Collection(name="Root"))
    admin = django_user_model.objects.create_superuser(username="race-admin", password="password")
    item = case.create_item(user=admin, collection=collection, title="Reviewed A")
    client = Client()
    client.force_login(admin)
    token = get_confirmation(client, case, item)

    written = threading.Event()
    release = threading.Event()
    delete_started = threading.Event()
    connections = []

    def replace():
        close_old_connections()
        try:
            with transaction.atomic():
                connection.ensure_connection()
                connections.append(connection.connection)
                fields = {"modified": timezone.now()} if case.model is not Transcript else {}
                fields["title" if case.model is not Transcript else "source_fingerprint"] = "replacement-b"
                case.model.objects.filter(pk=item.pk).update(**fields)
                written.set()
                assert release.wait(10)
        finally:
            close_old_connections()

    def delete():
        close_old_connections()
        try:
            connection.ensure_connection()
            connections.append(connection.connection)
            delete_started.set()
            return client.post(media_admin_url(case, "delete", item), {"confirmation": token}).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(replace)
        try:
            assert written.wait(10)
            deleter = pool.submit(delete)
            assert delete_started.wait(10)
            finished_before_release = _done_within(deleter, 0.3)
        finally:
            release.set()
        writer.result(timeout=20)
        status = deleter.result(timeout=20)

    assert connections[0] is not connections[1]
    assert not finished_before_release
    assert status == 409
    assert case.model.objects.filter(pk=item.pk).exists()


def _done_within(future, seconds: float) -> bool:
    try:
        future.result(timeout=seconds)
    except TimeoutError:
        return False
    return True


@pytest.mark.django_db
def test_confirmation_digest_ignores_read_database_alias(admin_user, media_root_collection):
    """A confirmation rendered from a replica read must match the row loaded for writing."""
    item = MEDIA_ADMIN_CASES[0].create_item(user=admin_user, collection=media_root_collection, title="Reviewed A")
    written = Audio.objects.get(pk=item.pk)
    read = Audio.objects.get(pk=item.pk)
    read._state.db = "replica"

    token = media_views.sign_delete_confirmation(read, admin_user)

    assert media_views.delete_confirmation_matches(written, admin_user, token)
