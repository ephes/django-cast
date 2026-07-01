from collections.abc import Callable
from dataclasses import dataclass

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.test import RequestFactory
from django.urls import reverse
from wagtail.models import Collection, GroupCollectionPermission

from cast.models import Audio, Transcript, Video
from cast.views import audio as audio_views
from cast.views import transcript as transcript_views
from cast.views import video as video_views


@dataclass(frozen=True)
class MediaAdminCase:
    model: type
    namespace: str
    context_key: str
    create_item: Callable
    view_module: object


def create_audio_item(*, user, collection: Collection, title: str) -> Audio:
    audio = Audio(user=user, collection=collection, title=title)
    audio.save(duration=False, cache_file_sizes=False)
    return audio


def create_video_item(*, user, collection: Collection, title: str) -> Video:
    video = Video(user=user, collection=collection, title=title, original=ContentFile(b"video", name=f"{title}.mp4"))
    video.save(poster=False)
    return video


def create_transcript_item(*, user, collection: Collection, title: str) -> Transcript:
    audio = create_audio_item(user=user, collection=collection, title=title)
    return Transcript.objects.create(audio=audio, collection=collection)


MEDIA_ADMIN_CASES = (
    MediaAdminCase(Audio, "castaudio", "audios", create_audio_item, audio_views),
    MediaAdminCase(Video, "castvideo", "videos", create_video_item, video_views),
    MediaAdminCase(Transcript, "cast-transcript", "transcripts", create_transcript_item, transcript_views),
)


@pytest.fixture
def media_collections(db):
    root = Collection.get_first_root_node()
    assert root is not None
    permitted = root.add_child(instance=Collection(name="Permitted media"))
    forbidden = root.add_child(instance=Collection(name="Forbidden media"))
    return permitted, forbidden


@pytest.fixture
def media_owner(db):
    return get_user_model().objects.create_user(username="media-owner", password="password")


def create_limited_admin(*, model: type, collection: Collection, codenames: list[str]):
    user = get_user_model().objects.create_user(
        username=f"limited-{model._meta.model_name}-admin",
        password="password",
        is_staff=True,
    )
    group = Group.objects.create(name=f"Limited {model._meta.model_name} admins")
    group.permissions.add(Permission.objects.get(codename="access_admin", content_type__app_label="wagtailadmin"))
    for codename in codenames:
        permission = Permission.objects.get(
            codename=codename,
            content_type__app_label=model._meta.app_label,
            content_type__model=model._meta.model_name,
        )
        GroupCollectionPermission.objects.create(group=group, collection=collection, permission=permission)
    group.user_set.add(user)
    return user


def media_admin_codenames(case: MediaAdminCase) -> list[str]:
    model_name = case.model._meta.model_name
    return [f"add_{model_name}", f"change_{model_name}", f"choose_{model_name}", f"delete_{model_name}"]


def media_admin_url(case: MediaAdminCase, view_name: str, item=None) -> str:
    if item is None:
        return reverse(f"{case.namespace}:{view_name}")
    return reverse(f"{case.namespace}:{view_name}", args=(item.pk,))


@pytest.mark.django_db
@pytest.mark.parametrize("case", MEDIA_ADMIN_CASES)
def test_limited_media_admin_lists_and_chooses_only_permitted_collection(
    client, case: MediaAdminCase, media_collections, media_owner
):
    permitted, forbidden = media_collections
    allowed_item = case.create_item(user=media_owner, collection=permitted, title=f"allowed {case.namespace}")
    forbidden_item = case.create_item(user=media_owner, collection=forbidden, title=f"forbidden {case.namespace}")
    user = create_limited_admin(model=case.model, collection=permitted, codenames=media_admin_codenames(case))
    assert client.login(username=user.username, password="password")

    index_response = client.get(media_admin_url(case, "index"))
    chooser_response = client.get(media_admin_url(case, "chooser"), {"p": "1"})
    chosen_response = client.get(media_admin_url(case, "chosen", allowed_item))
    forbidden_chosen_response = client.get(media_admin_url(case, "chosen", forbidden_item))

    assert index_response.status_code == 200
    assert allowed_item in index_response.context[case.context_key]
    assert forbidden_item not in index_response.context[case.context_key]
    assert chooser_response.status_code == 200
    assert allowed_item in chooser_response.context[case.context_key]
    assert forbidden_item not in chooser_response.context[case.context_key]
    assert chosen_response.status_code == 200
    assert forbidden_chosen_response.status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize("case", MEDIA_ADMIN_CASES)
def test_limited_media_admin_cannot_edit_or_delete_forbidden_collection(
    client, case: MediaAdminCase, media_collections, media_owner
):
    permitted, forbidden = media_collections
    allowed_item = case.create_item(user=media_owner, collection=permitted, title=f"allowed {case.namespace}")
    forbidden_item = case.create_item(user=media_owner, collection=forbidden, title=f"forbidden {case.namespace}")
    user = create_limited_admin(model=case.model, collection=permitted, codenames=media_admin_codenames(case))
    assert client.login(username=user.username, password="password")

    assert client.get(media_admin_url(case, "edit", allowed_item)).status_code == 200
    assert client.get(media_admin_url(case, "delete", allowed_item)).status_code == 200
    assert client.get(media_admin_url(case, "edit", forbidden_item)).status_code == 404
    assert client.get(media_admin_url(case, "delete", forbidden_item)).status_code == 404
    post_response = client.post(media_admin_url(case, "delete", forbidden_item), {"delete": "yes"})

    assert post_response.status_code == 404
    forbidden_item.refresh_from_db()


@pytest.mark.django_db
@pytest.mark.parametrize("case", MEDIA_ADMIN_CASES)
def test_limited_media_admin_without_collection_permissions_cannot_reach_media_views(
    client, case: MediaAdminCase, media_collections
):
    permitted, _forbidden = media_collections
    user = create_limited_admin(model=case.model, collection=permitted, codenames=[])
    assert client.login(username=user.username, password="password")

    assert client.get(media_admin_url(case, "index")).status_code in {302, 403}
    assert client.get(media_admin_url(case, "add")).status_code in {302, 403}
    assert client.get(media_admin_url(case, "chooser")).status_code in {302, 403}
    assert client.get(media_admin_url(case, "chooser_upload")).status_code in {302, 403}

    request_factory = RequestFactory()
    for view_name in ("index", "add", "chooser", "chooser_upload"):
        request = request_factory.get(media_admin_url(case, view_name))
        request.user = user
        with pytest.raises(PermissionDenied):
            getattr(case.view_module, view_name)(request)
