import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.messages import get_messages
from django.test import RequestFactory
from django.urls import reverse

from cast.devdata import create_transcript
from cast.models import VoxhelmSettings
from cast.voxhelm import TranscriptGenerationResult, VoxhelmError
from cast.views import voxhelm as voxhelm_views


@pytest.fixture
def limited_admin_client(client):
    user = get_user_model().objects.create_user(
        username="limited-admin",
        password="password",
        is_staff=True,
    )
    group = Group.objects.create(name="Limited Admins")
    group.permissions.add(Permission.objects.get(codename="access_admin", content_type__app_label="wagtailadmin"))
    group.user_set.add(user)
    assert client.login(username="limited-admin", password="password")
    return client


@pytest.mark.django_db
def test_voxhelm_settings_edit_masks_and_preserves_token(admin_client, site):
    VoxhelmSettings.objects.update_or_create(
        site=site,
        defaults={
            "api_base": "https://voxhelm.example",
            "api_token": "very-secret-token",
            "model": "auto",
            "language": "",
        },
    )
    edit_url = reverse("wagtailsettings:edit", args=("cast", "voxhelmsettings", site.pk))

    response = admin_client.get(edit_url)

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "very-secret-token" not in content
    assert "Leave blank to keep the existing token" in content

    response = admin_client.post(
        edit_url,
        {
            "api_base": "https://voxhelm.internal",
            "api_token": "",
            "model": "whisper-1",
            "language": "de",
        },
        follow=True,
    )

    assert response.status_code == 200
    setting = VoxhelmSettings.for_site(site)
    assert setting.api_base == "https://voxhelm.internal"
    assert setting.api_token == "very-secret-token"
    assert setting.model == "whisper-1"
    assert setting.language == "de"

    response = admin_client.post(
        edit_url,
        {
            "api_base": "https://voxhelm.internal",
            "api_token": "replacement-token",
            "model": "whisper-1",
            "language": "de",
        },
        follow=True,
    )

    assert response.status_code == 200
    setting.refresh_from_db()
    assert setting.api_token == "replacement-token"


@pytest.mark.django_db
def test_voxhelm_settings_new_instance_allows_empty_token(admin_client, site):
    edit_url = reverse("wagtailsettings:edit", args=("cast", "voxhelmsettings", site.pk))

    response = admin_client.post(
        edit_url,
        {
            "api_base": "",
            "api_token": "",
            "model": "",
            "language": "",
        },
        follow=True,
    )

    assert response.status_code == 200
    assert VoxhelmSettings.for_site(site).api_token == ""


@pytest.mark.django_db
def test_episode_edit_page_shows_generate_transcript_action(admin_client, episode):
    response = admin_client.get(reverse("wagtailadmin_pages:edit", args=(episode.pk,)))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Generate transcript" in content
    assert reverse("cast-voxhelm:generate_episode", args=(episode.pk,)) in content


@pytest.mark.django_db
def test_audio_edit_page_shows_generate_transcript_action(admin_client, audio):
    response = admin_client.get(reverse("castaudio:edit", args=(audio.pk,)))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Generate transcript" in content
    assert reverse("cast-voxhelm:generate_audio", args=(audio.pk,)) in content


@pytest.mark.django_db
def test_generate_episode_transcript_from_wagtail_admin(admin_client, episode, mocker):
    audio = episode.podcast_audio
    assert audio is not None
    transcript = create_transcript(audio=audio)
    service_cls = mocker.patch("cast.views.voxhelm.VoxhelmTranscriptService")
    service_cls.return_value.generate_for_audio.return_value = TranscriptGenerationResult(
        transcript=transcript,
        created=True,
        job_id="job-1",
        source_url="https://media.example.com/episode.mp3",
    )

    response = admin_client.post(reverse("cast-voxhelm:generate_episode", args=(episode.pk,)), follow=True)

    assert response.status_code == 200
    service_cls.assert_called_once_with(request_or_site=episode.get_site())
    service_cls.return_value.generate_for_audio.assert_called_once_with(audio)
    messages = [message.message for message in get_messages(response.wsgi_request)]
    assert any("Transcript created for" in message and episode.title in message for message in messages)


@pytest.mark.django_db
def test_generate_audio_transcript_from_wagtail_admin(admin_client, episode, mocker):
    audio = episode.podcast_audio
    assert audio is not None
    transcript = create_transcript(audio=audio)
    service_cls = mocker.patch("cast.views.voxhelm.VoxhelmTranscriptService")
    service_cls.return_value.generate_for_audio.return_value = TranscriptGenerationResult(
        transcript=transcript,
        created=False,
        job_id="job-2",
        source_url="https://media.example.com/episode.mp3",
    )

    response = admin_client.post(reverse("cast-voxhelm:generate_audio", args=(audio.pk,)), follow=True)

    assert response.status_code == 200
    service_cls.assert_called_once_with(request_or_site=episode.get_site())
    service_cls.return_value.generate_for_audio.assert_called_once_with(audio)
    messages = [message.message for message in get_messages(response.wsgi_request)]
    assert any("Transcript updated for" in message and audio.title in message for message in messages)


@pytest.mark.django_db
def test_generate_audio_transcript_reports_errors(admin_client, episode, mocker):
    audio = episode.podcast_audio
    assert audio is not None
    service_cls = mocker.patch("cast.views.voxhelm.VoxhelmTranscriptService")
    service_cls.return_value.generate_for_audio.side_effect = VoxhelmError("upstream broke")

    response = admin_client.post(reverse("cast-voxhelm:generate_audio", args=(audio.pk,)), follow=True)

    assert response.status_code == 200
    messages = [message.message for message in get_messages(response.wsgi_request)]
    assert any("Transcript generation failed: upstream broke" in message for message in messages)


@pytest.mark.django_db
def test_generate_audio_transcript_falls_back_to_request_site(admin_client, audio, site, mocker):
    transcript = create_transcript(audio=audio)
    service_cls = mocker.patch("cast.views.voxhelm.VoxhelmTranscriptService")
    service_cls.return_value.generate_for_audio.return_value = TranscriptGenerationResult(
        transcript=transcript,
        created=True,
        job_id="job-3",
        source_url="https://media.example.com/episode.mp3",
    )

    response = admin_client.post(reverse("cast-voxhelm:generate_audio", args=(audio.pk,)), follow=True)

    assert response.status_code == 200
    service_cls.assert_called_once_with(request_or_site=site)


@pytest.mark.django_db
def test_generate_audio_transcript_requires_login(client, audio):
    response = client.post(reverse("cast-voxhelm:generate_audio", args=(audio.pk,)))

    assert response.status_code == 302
    assert reverse("wagtailadmin_login") in response.url


@pytest.mark.django_db
def test_generate_audio_transcript_denies_user_without_permissions(limited_admin_client, audio):
    response = limited_admin_client.post(reverse("cast-voxhelm:generate_audio", args=(audio.pk,)))

    assert response.status_code == 302
    assert response.url == reverse("wagtailadmin_home")


@pytest.mark.django_db
def test_generate_episode_transcript_denies_user_without_permissions(limited_admin_client, episode):
    response = limited_admin_client.post(reverse("cast-voxhelm:generate_episode", args=(episode.pk,)))

    assert response.status_code == 302
    assert response.url == reverse("wagtailadmin_home")


@pytest.mark.django_db
def test_episode_without_audio_hides_generate_transcript_action(admin_client, unpublished_episode_without_audio):
    response = admin_client.get(reverse("wagtailadmin_pages:edit", args=(unpublished_episode_without_audio.pk,)))

    assert response.status_code == 200
    assert "Generate transcript" not in response.content.decode("utf-8")


@pytest.mark.django_db
def test_generate_episode_transcript_denies_when_audio_is_missing(
    admin_client, unpublished_episode_without_audio, mocker
):
    mocker.patch("cast.views.voxhelm.user_can_generate_transcript_for_episode", return_value=True)

    response = admin_client.post(
        reverse("cast-voxhelm:generate_episode", args=(unpublished_episode_without_audio.pk,))
    )

    assert response.status_code == 302
    assert response.url == reverse("wagtailadmin_home")


@pytest.mark.django_db
def test_generate_episode_transcript_reports_errors(admin_client, episode, mocker):
    audio = episode.podcast_audio
    assert audio is not None
    service_cls = mocker.patch("cast.views.voxhelm.VoxhelmTranscriptService")
    service_cls.return_value.generate_for_audio.side_effect = VoxhelmError("episode broke")

    response = admin_client.post(reverse("cast-voxhelm:generate_episode", args=(episode.pk,)), follow=True)

    assert response.status_code == 200
    messages = [message.message for message in get_messages(response.wsgi_request)]
    assert any("Transcript generation failed: episode broke" in message for message in messages)


def test_get_redirect_url_prefers_safe_next():
    request = RequestFactory().post("/", {"next": "/cms/pages/1/edit/"})

    assert voxhelm_views._get_redirect_url(request, "/fallback/") == "/cms/pages/1/edit/"


@pytest.mark.django_db
def test_user_can_generate_transcript_for_episode_returns_false_without_page_permissions(user, episode):
    request = RequestFactory().get("/")
    request.user = user

    assert voxhelm_views.user_can_generate_transcript_for_episode(request=request, episode=episode) is False
