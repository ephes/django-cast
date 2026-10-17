import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import Permission
from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils import timezone

from cast.api.editor import media as editor_media
from cast.devdata import create_transcript
from cast.models import (
    Audio,
    Contributor,
    EpisodeContributor,
    TranscriptGeneration,
    TranscriptSpeakerMapping,
    VoxhelmSettings,
)
from cast.voxhelm import TranscriptSubmission, VoxhelmError, build_audio_task_ref
from tests.factories import UserFactory


class _FakeScopedToken:
    def __init__(self, scope: str):
        self.scope = scope


@pytest.fixture
def voxhelm_env(settings, monkeypatch):
    """Production-like configuration: credentials and booleans only in the environment."""
    for name in (
        "CAST_VOXHELM_API_BASE",
        "CAST_VOXHELM_API_KEY",
        "CAST_VOXHELM_DIARIZATION_ENABLED",
        "CAST_VOXHELM_KNOWN_SPEAKER_ENABLED",
    ):
        if hasattr(settings, name):
            delattr(settings, name)
    monkeypatch.setenv("CAST_VOXHELM_API_BASE", "https://voxhelm.example")
    monkeypatch.setenv("CAST_VOXHELM_API_KEY", "secret")
    monkeypatch.setenv("CAST_VOXHELM_DIARIZATION_ENABLED", "true")
    monkeypatch.setenv("CAST_VOXHELM_KNOWN_SPEAKER_ENABLED", "true")
    return monkeypatch


@pytest.fixture
def draft_hosts(episode):
    """Two hosts credited on the latest draft revision only."""
    hosts = [
        Contributor.objects.create(display_name="Draft Host", slug="draft-host"),
        Contributor.objects.create(display_name="Guest", slug="guest"),
    ]
    for index, contributor in enumerate(hosts):
        episode.contributor_assignments.add(
            EpisodeContributor(contributor=contributor, role=EpisodeContributor.ROLE_HOST, sort_order=index)
        )
    episode.save_revision()
    EpisodeContributor.objects.filter(episode=episode).delete()
    return hosts


@pytest.fixture
def mock_voxhelm(mocker):
    def submit(audio, *, task_ref, episode):
        return TranscriptSubmission(
            job_id="job-1",
            source_url="https://media.example.com/audio.m4a",
            task_ref=task_ref,
            job_payload={"id": "job-1", "state": "queued"},
        )

    submit_mock = mocker.patch("cast.voxhelm.VoxhelmTranscriptService.submit_for_audio", side_effect=submit)
    enqueue_mock = mocker.Mock(return_value=SimpleNamespace(id="task-1"))
    mocker.patch("cast.voxhelm_tasks.complete_transcript_generation", new=SimpleNamespace(enqueue=enqueue_mock))
    return submit_mock


def transcript_url(episode) -> str:
    return reverse("cast:api:editor_episode_transcript", kwargs={"pk": episode.pk})


class TestEpisodeTranscriptGenerate:
    pytestmark = pytest.mark.django_db

    def test_enqueues_diarized_generation_with_draft_speaker_count(
        self, api_client, admin_user, episode, draft_hosts, voxhelm_env, mock_voxhelm
    ):
        # An existing site row with unset booleans must inherit the environment.
        VoxhelmSettings.objects.update_or_create(
            site=episode.get_site(), defaults={"diarization_enabled": None, "known_speaker_enabled": None}
        )
        api_client.force_authenticate(user=admin_user)

        response = api_client.post(transcript_url(episode))

        assert response.status_code == 202, response.content
        data = response.json()
        audio = episode.podcast_audio
        expected_task_ref = build_audio_task_ref(audio.pk, diarization_enabled=True, diarization_speaker_count=2)
        assert data["enqueued"] is True
        assert data["episode"] == {"id": episode.pk}
        assert data["audio"] == {"id": audio.pk}
        assert data["generation"]["status"] == "queued"
        assert data["generation"]["active"] is True
        assert data["generation"]["task_ref"] == expected_task_ref
        assert data["generation"]["voxhelm_job_id"] == "job-1"
        assert data["configuration"] == {
            "voxhelm_configured": True,
            "diarization": {"enabled": True, "source": "environment"},
            "known_speaker": {"enabled": True, "source": "environment"},
            "transcript_diarization_mode": "inherit",
            "diarize": True,
            "expected_speaker_count": 2,
            "known_speaker_count": 0,
        }
        assert data["transcript"] is None
        assert mock_voxhelm.call_args.kwargs["episode"].pk == episode.pk
        generation = TranscriptGeneration.objects.get(audio=audio)
        assert generation.requested_by == admin_user

        again = api_client.post(transcript_url(episode))
        assert again.status_code == 202
        assert again.json()["enqueued"] is False
        assert again.json()["generation"]["status"] == "queued"
        mock_voxhelm.assert_called_once()

    def test_requires_podcast_audio(self, api_client, admin_user, unpublished_episode_without_audio):
        api_client.force_authenticate(user=admin_user)
        response = api_client.post(transcript_url(unpublished_episode_without_audio))
        assert response.status_code == 400
        assert response.json()["errors"]["podcast_audio"][0]["code"] == "required"

    def test_requires_audio_change_permission(self, api_client, admin_user, episode, mocker, mock_voxhelm):
        mocker.patch.object(
            editor_media.audio_permission_policy, "user_has_permission_for_instance", return_value=False
        )
        api_client.force_authenticate(user=admin_user)
        response = api_client.post(transcript_url(episode))
        assert response.status_code == 403
        assert response.json()["code"] == "permission_denied"
        mock_voxhelm.assert_not_called()

    def test_requires_page_edit_permission_and_an_episode(self, api_client, episode, post, admin_user):
        user = UserFactory(is_staff=True)
        user.user_permissions.add(
            Permission.objects.get(codename="access_admin", content_type__app_label="wagtailadmin")
        )
        api_client.force_authenticate(user=user)
        assert api_client.post(transcript_url(episode)).status_code == 403
        assert api_client.get(transcript_url(episode)).status_code == 403

        api_client.force_authenticate(user=admin_user)
        not_episode = api_client.get(reverse("cast:api:editor_episode_transcript", kwargs={"pk": post.pk}))
        assert not_episode.status_code == 404
        assert not_episode.json()["code"] == "not_found"

    def test_reports_missing_voxhelm_configuration(self, api_client, admin_user, episode, settings, monkeypatch):
        for name in ("CAST_VOXHELM_API_BASE", "CAST_VOXHELM_API_KEY"):
            if hasattr(settings, name):
                delattr(settings, name)
            monkeypatch.delenv(name, raising=False)
        api_client.force_authenticate(user=admin_user)

        response = api_client.post(transcript_url(episode))

        assert response.status_code == 409
        assert response.json()["code"] == "voxhelm_not_configured"
        assert "CAST_VOXHELM_API_BASE" in response.json()["detail"]
        assert not TranscriptGeneration.objects.exists()

    def test_reports_voxhelm_failures(self, api_client, admin_user, episode, voxhelm_env, mocker):
        mocker.patch(
            "cast.voxhelm.VoxhelmTranscriptService.submit_for_audio", side_effect=VoxhelmError("upstream broke")
        )
        api_client.force_authenticate(user=admin_user)

        response = api_client.post(transcript_url(episode))

        assert response.status_code == 502
        assert response.json() == {"code": "voxhelm_error", "detail": "Transcript generation failed: upstream broke"}
        assert TranscriptGeneration.objects.get(audio=episode.podcast_audio).status == "failed"

    def test_write_scope_is_required(self, api_client, admin_user, episode, voxhelm_env, mock_voxhelm):
        api_client.force_authenticate(user=admin_user, token=_FakeScopedToken("publish"))
        denied = api_client.post(transcript_url(episode))
        assert denied.status_code == 403
        assert denied.json()["code"] == "insufficient_scope"
        assert api_client.get(transcript_url(episode)).status_code == 200

        api_client.force_authenticate(user=admin_user, token=_FakeScopedToken("write"))
        assert api_client.post(transcript_url(episode)).status_code == 202

    def test_options_lists_post(self, api_client, admin_user, episode):
        api_client.force_authenticate(user=admin_user)
        response = api_client.options(transcript_url(episode))
        assert response.status_code == 200
        assert "POST" in response["Allow"]


class TestEpisodeTranscriptStatus:
    pytestmark = pytest.mark.django_db

    def test_status_without_generation_or_transcript(self, api_client, admin_user, episode, voxhelm_env):
        api_client.force_authenticate(user=admin_user)
        response = api_client.get(transcript_url(episode))
        assert response.status_code == 200
        data = response.json()
        assert data["generation"] is None
        assert data["transcript"] is None
        assert data["configuration"]["expected_speaker_count"] is None

    def test_status_without_podcast_audio(self, api_client, admin_user, unpublished_episode_without_audio):
        api_client.force_authenticate(user=admin_user)
        data = api_client.get(transcript_url(unpublished_episode_without_audio)).json()
        assert data["audio"] is None
        assert data["generation"] is None
        assert data["configuration"]["transcript_diarization_mode"] is None

    def test_site_override_and_audio_modes_are_reported(self, api_client, admin_user, episode, voxhelm_env):
        VoxhelmSettings.objects.update_or_create(site=episode.get_site(), defaults={"diarization_enabled": False})
        api_client.force_authenticate(user=admin_user)

        inherit = api_client.get(transcript_url(episode)).json()["configuration"]
        assert inherit["diarization"] == {"enabled": False, "source": "site"}
        assert inherit["diarize"] is False
        assert inherit["known_speaker_count"] == 0

        audio = episode.podcast_audio
        audio.transcript_diarization_mode = Audio.TranscriptDiarizationMode.ENABLED
        audio.save(update_fields=["transcript_diarization_mode"], duration=False, cache_file_sizes=False)
        assert api_client.get(transcript_url(episode)).json()["configuration"]["diarize"] is True

        audio.transcript_diarization_mode = Audio.TranscriptDiarizationMode.DISABLED
        audio.save(update_fields=["transcript_diarization_mode"], duration=False, cache_file_sizes=False)
        VoxhelmSettings.objects.filter(site=episode.get_site()).update(diarization_enabled=True)
        assert api_client.get(transcript_url(episode)).json()["configuration"]["diarize"] is False

    def test_invalid_boolean_configuration_is_reported(self, api_client, admin_user, episode, voxhelm_env):
        voxhelm_env.setenv("CAST_VOXHELM_DIARIZATION_ENABLED", "sometimes")
        api_client.force_authenticate(user=admin_user)
        configuration = api_client.get(transcript_url(episode)).json()["configuration"]
        assert configuration["diarization"]["enabled"] is None
        assert configuration["diarization"]["source"] == "invalid"
        assert "CAST_VOXHELM_DIARIZATION_ENABLED" in configuration["diarization"]["error"]
        assert configuration["diarize"] is False

    def test_interrupted_generation_is_not_active(self, api_client, admin_user, episode, settings):
        settings.CAST_VOXHELM_STALE_AFTER = 1
        generation = TranscriptGeneration.objects.create(
            audio=episode.podcast_audio, task_ref="audio:1", status=TranscriptGeneration.Status.RUNNING
        )
        TranscriptGeneration.objects.filter(pk=generation.pk).update(
            started_at=timezone.now() - timedelta(hours=1), updated_at=timezone.now() - timedelta(hours=1)
        )
        api_client.force_authenticate(user=admin_user)
        data = api_client.get(transcript_url(episode)).json()["generation"]
        assert data["status"] == "interrupted"
        assert data["active"] is False

    def test_transcript_speakers_and_editor_preview_labels(self, api_client, admin_user, episode, draft_hosts):
        episode.live = False
        episode.save(update_fields=["live"])
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={
                "transcripts": [
                    {"start": "00:00:00.000", "speaker": "Draft Host", "voice": "Draft Host", "text": "A"},
                    {"start": "00:00:01.000", "speaker": "Speaker 2", "voice": "Speaker 2", "text": "B"},
                    {"start": "00:00:02.000", "speaker": "Speaker 3", "voice": "Speaker 3", "text": "C"},
                ]
            },
        )
        transcript.speakers.save(
            "speakers.json",
            ContentFile(
                json.dumps(
                    {
                        "segments": [
                            {"start": 0.0, "speaker": "Draft Host", "speaker_uncertain": False},
                            {"start": 1.0, "speaker": "Guest", "speaker_uncertain": False},
                            {"start": 2.0, "speaker": "Guest", "speaker_uncertain": True},
                        ],
                        "summary": {"strategy": "test"},
                    }
                ).encode()
            ),
        )
        transcript.sync_speaker_mappings()
        TranscriptSpeakerMapping.objects.filter(transcript=transcript, speaker_label="Speaker 2").update(
            contributor=draft_hosts[1],
            review_state=TranscriptSpeakerMapping.ReviewState.APPROVED,
            source_artifact_fingerprint=transcript.transcript_artifact_fingerprint(),
        )
        api_client.force_authenticate(user=admin_user)

        data = api_client.get(transcript_url(episode)).json()["transcript"]

        assert data["id"] == transcript.pk
        assert data["complete"] is False
        assert data["edit_url"] == reverse("cast-transcript:edit", args=(transcript.pk,))
        assert data["speaker_labels"] == ["Draft Host", "Speaker 2", "Speaker 3"]
        assert data["preview_speaker_labels"] == ["Draft Host", "Guest"]
        assert data["known_speaker_suggestions"] == {
            "total": 3,
            "confident": 2,
            "uncertain": 1,
            "by_speaker": {"Draft Host": 1, "Guest": 1},
        }
        mappings = {row["speaker_label"]: row for row in data["speaker_mappings"]}
        assert mappings["Speaker 2"] == {
            "speaker_label": "Speaker 2",
            "review_state": "approved",
            "contributor": {"id": draft_hosts[1].pk, "slug": "guest"},
            "display_name": "Guest",
        }
        assert mappings["Speaker 3"]["contributor"] is None

    def test_live_episode_reports_public_labels(self, api_client, admin_user, episode):
        contributor = Contributor.objects.create(display_name="Live Host", slug="live-host")
        EpisodeContributor.objects.create(episode=episode, contributor=contributor, role=EpisodeContributor.ROLE_HOST)
        create_transcript(
            audio=episode.podcast_audio,
            podlove={"transcripts": [{"start": "00:00:00.000", "speaker": "Live Host", "text": "A"}]},
        )
        api_client.force_authenticate(user=admin_user)
        data = api_client.get(transcript_url(episode)).json()["transcript"]
        assert data["preview_speaker_labels"] == ["Live Host"]
        assert data["known_speaker_suggestions"] is None
