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
    if case.model is Transcript:
        grant_audio_choose(user, permitted)
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
    if case.model is Transcript:
        grant_audio_choose(user, permitted)
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


def grant_audio_choose(user, collection):
    permission = Permission.objects.get(codename="choose_audio", content_type__app_label="cast")
    GroupCollectionPermission.objects.create(group=user.groups.get(), collection=collection, permission=permission)


@pytest.fixture
def transcript_admin_access(media_collections, media_owner):
    permitted, forbidden = media_collections
    user = create_limited_admin(
        model=Transcript,
        collection=permitted,
        codenames=["add_transcript", "change_transcript", "choose_transcript", "delete_transcript"],
    )
    grant_audio_choose(user, permitted)
    allowed_audio = create_audio_item(user=media_owner, collection=permitted, title="allowed audio")
    forbidden_audio = create_audio_item(user=media_owner, collection=forbidden, title="forbidden audio")
    return user, allowed_audio, forbidden_audio


@pytest.mark.django_db
@pytest.mark.parametrize("view_name", ["add", "chooser_upload", "edit"])
def test_transcript_admin_rejects_forbidden_audio_post(client, transcript_admin_access, view_name):
    user, allowed_audio, forbidden_audio = transcript_admin_access
    client.force_login(user)
    transcript = None
    if view_name == "edit":
        transcript = Transcript.objects.create(audio=allowed_audio, collection=allowed_audio.collection)
    url = reverse(f"cast-transcript:{view_name}", args=(transcript.pk,) if transcript else ())
    prefix = "media-chooser-upload-" if view_name == "chooser_upload" else ""
    response = client.post(url, {f"{prefix}audio": forbidden_audio.pk})
    assert response.status_code == 200
    assert not Transcript.objects.filter(audio=forbidden_audio).exists()
    if transcript:
        transcript.refresh_from_db()
        assert transcript.audio_id == allowed_audio.pk
    assert forbidden_audio.title not in response.content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize("view_name", ["add", "chooser_upload", "edit"])
def test_transcript_admin_accepts_allowed_audio_post(client, transcript_admin_access, view_name):
    user, allowed_audio, _forbidden_audio = transcript_admin_access
    client.force_login(user)
    transcript = None
    if view_name == "edit":
        original_audio = create_audio_item(user=user, collection=allowed_audio.collection, title="original audio")
        transcript = Transcript.objects.create(audio=original_audio, collection=allowed_audio.collection)
    url = reverse(f"cast-transcript:{view_name}", args=(transcript.pk,) if transcript else ())
    prefix = "media-chooser-upload-" if view_name == "chooser_upload" else ""
    response = client.post(url, {f"{prefix}audio": allowed_audio.pk})
    assert response.status_code == (200 if view_name == "chooser_upload" else 302)
    saved = Transcript.objects.get(audio=allowed_audio)
    assert saved.collection_id == allowed_audio.collection_id
    if transcript:
        assert saved.pk == transcript.pk


@pytest.mark.django_db
@pytest.mark.parametrize("view_name", ["edit", "delete", "chosen"])
@pytest.mark.parametrize("method", ["get", "post"])
def test_existing_forbidden_transcript_is_inaccessible(client, transcript_admin_access, view_name, method):
    user, allowed_audio, forbidden_audio = transcript_admin_access
    transcript = Transcript.objects.create(audio=forbidden_audio, collection=allowed_audio.collection)
    client.force_login(user)
    response = getattr(client, method)(reverse(f"cast-transcript:{view_name}", args=(transcript.pk,)))
    assert response.status_code == 404
    assert forbidden_audio.title not in response.content.decode()
    transcript.refresh_from_db()
    assert transcript.audio_id == forbidden_audio.pk


@pytest.mark.django_db
@pytest.mark.parametrize("action", list(transcript_views.EDIT_ACTION_HANDLERS))
def test_existing_forbidden_transcript_cannot_run_edit_actions(client, transcript_admin_access, action, mocker):
    user, allowed_audio, forbidden_audio = transcript_admin_access
    transcript = Transcript.objects.create(audio=forbidden_audio, collection=allowed_audio.collection)
    handler = mocker.Mock()
    mocker.patch.dict(transcript_views.EDIT_ACTION_HANDLERS, {action: handler})
    client.force_login(user)
    response = client.post(reverse("cast-transcript:edit", args=(transcript.pk,)), {"action": action})
    assert response.status_code == 404
    handler.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize("view_name", ["index", "chooser"])
@pytest.mark.parametrize("query", ["", "audio"])
def test_existing_forbidden_transcript_is_not_listed(client, transcript_admin_access, view_name, query):
    user, allowed_audio, forbidden_audio = transcript_admin_access
    allowed_transcript = Transcript.objects.create(audio=allowed_audio, collection=allowed_audio.collection)
    nonmatching_audio = create_audio_item(user=user, collection=allowed_audio.collection, title="Unrelated recording")
    nonmatching_transcript = Transcript.objects.create(audio=nonmatching_audio, collection=allowed_audio.collection)
    transcript = Transcript.objects.create(audio=forbidden_audio, collection=allowed_audio.collection)
    client.force_login(user)
    response = client.get(reverse(f"cast-transcript:{view_name}"), {"p": "1", "q": query})
    assert response.status_code == 200
    assert allowed_transcript in response.context["transcripts"]
    assert (nonmatching_transcript in response.context["transcripts"]) == (not query)
    assert transcript not in response.context["transcripts"]
    assert allowed_audio.title in response.content.decode()
    assert forbidden_audio.title not in response.content.decode()


@pytest.mark.django_db
def test_transcript_form_audio_choices_obey_chooser_policy(transcript_admin_access):
    from cast.forms import TranscriptForm

    user, allowed_audio, forbidden_audio = transcript_admin_access
    form = TranscriptForm(user=user)
    assert list(form.fields["audio"].queryset) == [allowed_audio]
    # Trusted callers without an acting user retain the programmatic form API.
    assert forbidden_audio in TranscriptForm().fields["audio"].queryset
    user.groups.get().collection_permissions.filter(permission__codename="choose_audio").delete()
    user = get_user_model().objects.get(pk=user.pk)
    assert not TranscriptForm(user=user).fields["audio"].queryset.exists()


@pytest.mark.django_db
def test_transcript_form_allows_inherited_audio_choose_permission(transcript_admin_access):
    from cast.forms import TranscriptForm

    user, allowed_audio, _forbidden_audio = transcript_admin_access
    child = allowed_audio.collection.add_child(instance=Collection(name="Allowed child"))
    allowed_audio.collection = child
    allowed_audio.save(duration=False, cache_file_sizes=False)
    form = TranscriptForm({"audio": allowed_audio.pk, "collection": child.pk}, user=user)
    assert form.is_valid(), form.errors


@pytest.mark.django_db
def test_transcript_instance_permissions_require_audio_choose(transcript_admin_access):
    user, allowed_audio, forbidden_audio = transcript_admin_access
    transcript = Transcript.objects.create(audio=forbidden_audio, collection=allowed_audio.collection)
    policy = transcript_views.transcript_permission_policy
    assert not policy.user_has_permission_for_instance(user, "change", transcript)
    assert not policy.user_has_any_permission_for_instance(user, ["change", "delete"], transcript)
    grant_audio_choose(user, forbidden_audio.collection)
    user = get_user_model().objects.get(pk=user.pk)
    assert policy.user_has_permission_for_instance(user, "change", transcript)


@pytest.mark.django_db
@pytest.mark.parametrize("superuser", [False, True])
def test_existing_cross_collection_transcript_can_be_managed_with_audio_access(
    client, transcript_admin_access, superuser
):
    user, allowed_audio, forbidden_audio = transcript_admin_access
    transcript = Transcript.objects.create(audio=forbidden_audio, collection=allowed_audio.collection)
    if superuser:
        user.is_superuser = True
        user.save(update_fields=["is_superuser"])
    else:
        grant_audio_choose(user, forbidden_audio.collection)
    client.force_login(user)
    edit_url = reverse("cast-transcript:edit", args=(transcript.pk,))
    response = client.get(edit_url)
    assert response.status_code == 200
    assert response.context["transcript"].pk == transcript.pk
    response = client.post(edit_url, {"audio": forbidden_audio.pk, "collection": allowed_audio.collection_id})
    assert response.status_code == 302
    transcript.refresh_from_db()
    assert transcript.audio_id == forbidden_audio.pk
    response = client.post(reverse("cast-transcript:delete", args=(transcript.pk,)), {"delete": "yes"})
    assert response.status_code == 302
    assert not Transcript.objects.filter(pk=transcript.pk).exists()
