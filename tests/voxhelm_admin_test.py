from urllib.parse import urlencode

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.messages import get_messages
from django.test import RequestFactory
from django.urls import reverse

from cast.models import Transcript, TranscriptGeneration, VoxhelmSettings
from cast.wagtail_hooks import GenerateEpisodeTranscriptMenuItem
from cast.voxhelm import VoxhelmError, build_audio_task_ref
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
            "diarization_enabled": True,
        },
    )
    edit_url = reverse("wagtailsettings:edit", args=("cast", "voxhelmsettings", site.pk))

    response = admin_client.get(edit_url)

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "very-secret-token" not in content
    assert "A token is configured" in content
    assert "Leave blank to keep the existing token" in content

    response = admin_client.post(
        edit_url,
        {
            "api_base": "https://voxhelm.internal",
            "api_token": "",
            "model": "whisper-1",
            "language": "de",
            "diarization_enabled": "false",
        },
        follow=True,
    )

    assert response.status_code == 200
    setting = VoxhelmSettings.for_site(site)
    assert setting.api_base == "https://voxhelm.internal"
    assert setting.api_token == "very-secret-token"
    assert setting.model == "whisper-1"
    assert setting.language == "de"
    assert setting.diarization_enabled is False

    response = admin_client.post(
        edit_url,
        {
            "api_base": "https://voxhelm.internal",
            "api_token": "replacement-token",
            "model": "whisper-1",
            "language": "de",
            "diarization_enabled": "true",
        },
        follow=True,
    )

    assert response.status_code == 200
    setting.refresh_from_db()
    assert setting.api_token == "replacement-token"
    assert setting.diarization_enabled is True


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
            "diarization_enabled": "unknown",
        },
        follow=True,
    )

    assert response.status_code == 200
    setting = VoxhelmSettings.for_site(site)
    assert setting.api_token == ""
    assert setting.diarization_enabled is None


@pytest.mark.django_db
def test_episode_edit_page_shows_generate_transcript_action(admin_client, episode):
    edit_url = reverse("wagtailadmin_pages:edit", args=(episode.pk,))
    response = admin_client.get(f"{edit_url}?show=comments&tab=content")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    expected_action = f"{reverse('cast-voxhelm:generate_episode', args=(episode.pk,))}?{urlencode({'next': f'{edit_url}?show=comments&tab=content'})}"
    assert "Generate transcript" in content
    assert expected_action in content
    assert "button-secondary button-longrunning" not in content


@pytest.mark.django_db
def test_episode_edit_page_shows_transcript_generation_status(admin_client, episode):
    audio = episode.podcast_audio
    assert audio is not None
    TranscriptGeneration.objects.create(
        audio=audio,
        status=TranscriptGeneration.Status.RUNNING,
        task_ref=build_audio_task_ref(audio.pk),
        voxhelm_job_id="job-episode",
    )

    response = admin_client.get(reverse("wagtailadmin_pages:edit", args=(episode.pk,)))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Transcript status:" in content
    assert "Running" in content
    assert 'class="cast-transcript-status w-mb-4"' in content
    assert '<a role="status">' not in content
    assert 'class="help-block"' not in content


@pytest.mark.django_db
def test_episode_edit_page_links_succeeded_transcript(admin_client, episode):
    audio = episode.podcast_audio
    assert audio is not None
    transcript = Transcript.objects.create(audio=audio)
    TranscriptGeneration.objects.create(
        audio=audio,
        status=TranscriptGeneration.Status.SUCCEEDED,
        task_ref=build_audio_task_ref(audio.pk),
        voxhelm_job_id="job-episode",
    )

    response = admin_client.get(reverse("wagtailadmin_pages:edit", args=(episode.pk,)))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Succeeded" in content
    assert "Edit transcript" in content
    assert reverse("cast-transcript:edit", args=(transcript.pk,)) in content
    assert '<a role="status">' not in content


@pytest.mark.django_db
def test_audio_edit_page_shows_generate_transcript_action(admin_client, audio):
    response = admin_client.get(reverse("castaudio:edit", args=(audio.pk,)))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Generate transcript" in content
    assert reverse("cast-voxhelm:generate_audio", args=(audio.pk,)) in content
    assert 'class="button button-secondary"' in content
    assert "button-longrunning" not in content


@pytest.mark.django_db
def test_audio_edit_page_shows_transcript_generation_status(admin_client, audio):
    TranscriptGeneration.objects.create(
        audio=audio,
        status=TranscriptGeneration.Status.FAILED,
        task_ref=build_audio_task_ref(audio.pk),
        error_message="upstream broke",
    )

    response = admin_client.get(reverse("castaudio:edit", args=(audio.pk,)))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Transcript status:" in content
    assert "Failed" in content
    assert "upstream broke" in content
    assert 'class="cast-transcript-status"' in content
    assert 'class="help-block"' not in content


@pytest.mark.django_db
def test_generate_episode_transcript_from_wagtail_admin(admin_client, episode, mocker):
    audio = episode.podcast_audio
    assert audio is not None
    generation = TranscriptGeneration.objects.create(
        audio=audio,
        status=TranscriptGeneration.Status.QUEUED,
        task_ref=build_audio_task_ref(audio.pk),
    )
    enqueue = mocker.patch(
        "cast.views.voxhelm.enqueue_audio_transcript_generation",
        return_value=type("Result", (), {"generation": generation, "enqueued": True})(),
    )

    edit_url = reverse("wagtailadmin_pages:edit", args=(episode.pk,))
    response = admin_client.post(
        f"{reverse('cast-voxhelm:generate_episode', args=(episode.pk,))}?next={edit_url}", follow=True
    )

    assert response.status_code == 200
    assert response.redirect_chain[0][0] == edit_url
    enqueue.assert_called_once_with(audio=audio, request_or_site=episode.get_site(), requested_by=mocker.ANY)
    messages = [message.message for message in get_messages(response.wsgi_request)]
    assert any("Transcript generation queued for" in message and episode.title in message for message in messages)


@pytest.mark.django_db
def test_generate_audio_transcript_from_wagtail_admin(admin_client, episode, mocker):
    audio = episode.podcast_audio
    assert audio is not None
    generation = TranscriptGeneration.objects.create(
        audio=audio,
        status=TranscriptGeneration.Status.QUEUED,
        task_ref=build_audio_task_ref(audio.pk),
    )
    enqueue = mocker.patch(
        "cast.views.voxhelm.enqueue_audio_transcript_generation",
        return_value=type("Result", (), {"generation": generation, "enqueued": True})(),
    )

    response = admin_client.post(reverse("cast-voxhelm:generate_audio", args=(audio.pk,)), follow=True)

    assert response.status_code == 200
    enqueue.assert_called_once_with(audio=audio, request_or_site=episode.get_site(), requested_by=mocker.ANY)
    messages = [message.message for message in get_messages(response.wsgi_request)]
    assert any("Transcript generation queued for" in message and audio.title in message for message in messages)
    content = response.content.decode("utf-8")
    assert "Save" in content
    assert "Transcript status:" in content
    assert "Queued" in content


@pytest.mark.django_db
def test_generate_audio_transcript_reports_errors(admin_client, episode, mocker):
    audio = episode.podcast_audio
    assert audio is not None
    enqueue = mocker.patch("cast.views.voxhelm.enqueue_audio_transcript_generation")
    enqueue.side_effect = VoxhelmError("upstream broke")

    response = admin_client.post(reverse("cast-voxhelm:generate_audio", args=(audio.pk,)), follow=True)

    assert response.status_code == 200
    messages = [message.message for message in get_messages(response.wsgi_request)]
    assert any("Transcript generation failed: upstream broke" in message for message in messages)


@pytest.mark.django_db
def test_generate_episode_transcript_reports_missing_site_token(admin_client, episode, settings, monkeypatch):
    audio = episode.podcast_audio
    assert audio is not None
    site = episode.get_site()
    assert site is not None
    settings.CAST_VOXHELM_API_KEY = ""
    monkeypatch.delenv("CAST_VOXHELM_API_KEY", raising=False)
    VoxhelmSettings.objects.update_or_create(
        site=site,
        defaults={
            "api_base": "https://voxhelm.example",
            "api_token": "",
        },
    )

    response = admin_client.post(reverse("cast-voxhelm:generate_episode", args=(episode.pk,)), follow=True)

    assert response.status_code == 200
    messages = [message.message for message in get_messages(response.wsgi_request)]
    assert any(
        "Transcript generation failed: CAST_VOXHELM_API_KEY must be configured" in message for message in messages
    )
    assert any("Voxhelm settings" in message for message in messages)


@pytest.mark.django_db
def test_generate_audio_transcript_reports_missing_api_base(admin_client, audio, settings, monkeypatch):
    settings.CAST_VOXHELM_API_BASE = ""
    settings.CAST_VOXHELM_API_KEY = "secret"
    monkeypatch.delenv("CAST_VOXHELM_API_BASE", raising=False)

    response = admin_client.post(reverse("cast-voxhelm:generate_audio", args=(audio.pk,)), follow=True)

    assert response.status_code == 200
    messages = [message.message for message in get_messages(response.wsgi_request)]
    assert any(
        "Transcript generation failed: CAST_VOXHELM_API_BASE must be configured" in message for message in messages
    )


@pytest.mark.django_db
def test_generate_audio_transcript_reports_invalid_boolean_setting(admin_client, audio, settings):
    settings.CAST_VOXHELM_API_BASE = "https://voxhelm.example"
    settings.CAST_VOXHELM_API_KEY = "secret"
    settings.CAST_VOXHELM_DIARIZATION_ENABLED = "sometimes"

    response = admin_client.post(reverse("cast-voxhelm:generate_audio", args=(audio.pk,)), follow=True)

    assert response.status_code == 200
    messages = [message.message for message in get_messages(response.wsgi_request)]
    assert any(
        "Transcript generation failed: CAST_VOXHELM_DIARIZATION_ENABLED must be configured as a boolean value"
        in message
        for message in messages
    )


@pytest.mark.django_db
def test_generate_audio_transcript_reports_invalid_numeric_setting(admin_client, audio, settings):
    settings.CAST_VOXHELM_API_BASE = "https://voxhelm.example"
    settings.CAST_VOXHELM_API_KEY = "secret"
    settings.CAST_VOXHELM_POLL_TIMEOUT = "6h"

    response = admin_client.post(reverse("cast-voxhelm:generate_audio", args=(audio.pk,)), follow=True)

    assert response.status_code == 200
    messages = [message.message for message in get_messages(response.wsgi_request)]
    assert any(
        "Transcript generation failed: CAST_VOXHELM_POLL_TIMEOUT must be configured as a numeric value" in message
        for message in messages
    )


@pytest.mark.django_db
def test_generate_audio_transcript_falls_back_to_request_site(admin_client, audio, site, mocker):
    generation = TranscriptGeneration.objects.create(
        audio=audio,
        status=TranscriptGeneration.Status.QUEUED,
        task_ref=build_audio_task_ref(audio.pk),
    )
    enqueue = mocker.patch(
        "cast.views.voxhelm.enqueue_audio_transcript_generation",
        return_value=type("Result", (), {"generation": generation, "enqueued": True})(),
    )

    response = admin_client.post(reverse("cast-voxhelm:generate_audio", args=(audio.pk,)), follow=True)

    assert response.status_code == 200
    enqueue.assert_called_once_with(audio=audio, request_or_site=site, requested_by=mocker.ANY)


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


def test_generate_episode_transcript_menu_item_context_handles_missing_audio(user, unpublished_episode_without_audio):
    request = RequestFactory().get("/")
    request.user = user
    item = GenerateEpisodeTranscriptMenuItem(order=70)

    context = item.get_context_data(
        {
            "request": request,
            "page": unpublished_episode_without_audio,
            "view": "edit",
            "locked_for_user": False,
        }
    )

    assert context["transcript_generation_active"] is False
    assert "transcript_generation_status" not in context
    assert "transcript_generation_message" not in context


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
    enqueue = mocker.patch("cast.views.voxhelm.enqueue_audio_transcript_generation")
    enqueue.side_effect = VoxhelmError("episode broke")

    response = admin_client.post(reverse("cast-voxhelm:generate_episode", args=(episode.pk,)), follow=True)

    assert response.status_code == 200
    messages = [message.message for message in get_messages(response.wsgi_request)]
    assert any("Transcript generation failed: episode broke" in message for message in messages)


@pytest.mark.django_db
def test_generate_audio_transcript_duplicate_submission_reports_in_progress(admin_client, audio):
    TranscriptGeneration.objects.create(
        audio=audio,
        status=TranscriptGeneration.Status.RUNNING,
        task_ref=build_audio_task_ref(audio.pk),
        voxhelm_job_id="job-running",
        task_result_id="task-running",
    )

    response = admin_client.post(reverse("cast-voxhelm:generate_audio", args=(audio.pk,)), follow=True)

    assert response.status_code == 200
    messages = [message.message for message in get_messages(response.wsgi_request)]
    assert any("already in progress" in message for message in messages)


def test_get_redirect_url_prefers_safe_next():
    request = RequestFactory().post("/", {"next": "/cms/pages/1/edit/"})

    assert voxhelm_views._get_redirect_url(request, "/fallback/") == "/cms/pages/1/edit/"


def test_get_redirect_url_rejects_protocol_relative_next():
    request = RequestFactory().post("/", {"next": "//evil.example/cms/pages/1/edit/"})

    assert voxhelm_views._get_redirect_url(request, "/fallback/") == "/fallback/"


@pytest.mark.django_db
def test_user_can_generate_transcript_for_episode_returns_false_without_page_permissions(user, episode):
    request = RequestFactory().get("/")
    request.user = user

    assert voxhelm_views.user_can_generate_transcript_for_episode(request=request, episode=episode) is False
