"""Synthetic stale-form and synchronous generation interleavings."""

import pytest
from django.core.exceptions import ValidationError
from django.forms import modelform_factory

from cast.models import TranscriptGeneration, VoxhelmSettings
from cast.models.voxhelm_settings import VoxhelmSettingsForm
from cast.voxhelm import TranscriptSubmission, VoxhelmTranscriptService
from cast.voxhelm.service import StaleTranscriptAttempt
from tests.known_speaker_apply_test import make_transcript
from tests.voxhelm.tasks_status_test import VALID_DOTE_ARTIFACT, VALID_PODLOVE_ARTIFACT, VALID_VTT_ARTIFACT


def settings_form(instance, **data):
    form_class = modelform_factory(VoxhelmSettings, form=VoxhelmSettingsForm, fields=["api_token", "language"])
    form = form_class(data={"api_token": "", "language": "de", **data}, instance=instance)
    assert form.is_valid(), form.errors
    return form


@pytest.mark.django_db
@pytest.mark.parametrize("current_token", ["rotated-synthetic", ""])
@pytest.mark.parametrize("commit", [True, False])
def test_blank_form_preserves_token_at_save(site, current_token, commit):
    setting = VoxhelmSettings.objects.create(site=site, api_token="old-synthetic")
    stale = settings_form(VoxhelmSettings.objects.get(pk=setting.pk))
    settings_form(setting, api_token=current_token, clear_api_token=not current_token, language="en").save()
    saved = stale.save(commit=commit)
    if not commit:
        saved.save()
    setting.refresh_from_db()
    assert setting.api_token == current_token
    assert setting.language == "de"


@pytest.mark.django_db
@pytest.mark.parametrize("clear", [True, False])
def test_explicit_token_change_refuses_stale_save(site, clear):
    setting = VoxhelmSettings.objects.create(site=site, api_token="old-synthetic")
    stale = settings_form(setting, api_token="" if clear else "replacement", clear_api_token=clear)
    VoxhelmSettings.objects.filter(pk=setting.pk).update(api_token="rotated")
    with pytest.raises(ValidationError, match="changed"):
        stale.save()
    setting.refresh_from_db()
    assert setting.api_token == "rotated"
    assert setting.language == ""


@pytest.mark.django_db
@pytest.mark.parametrize("replacement", ["queued", "editor"])
def test_cli_completion_refuses_newer_work(audio, mocker, replacement):
    transcript = make_transcript(audio, podlove={"transcripts": [{"speaker": "Speaker 1", "text": "current"}]})
    before = transcript.podlove.name
    transcript.sync_speaker_mappings()
    mapping = transcript.speaker_mappings.get()
    mapping.display_name = "Synthetic approved speaker"
    mapping.review_state = mapping.ReviewState.APPROVED
    mapping.save()
    mapping_state = list(transcript.speaker_mappings.values())
    current_files = []
    client = mocker.Mock()
    client.download_artifact.side_effect = [VALID_PODLOVE_ARTIFACT, VALID_DOTE_ARTIFACT, VALID_VTT_ARTIFACT]
    service = VoxhelmTranscriptService(client=client)

    def wait(job_id):
        if replacement == "queued":
            generation, _ = TranscriptGeneration.objects.get_or_create(audio=audio, defaults={"task_ref": "new"})
            generation.queue_submission(
                task_ref="new", voxhelm_job_id="new", source_url="", task_result_id="", site=None, requested_by=None
            )
            generation.mark_succeeded()
        else:
            from django.core.files.base import ContentFile

            transcript.podlove.save("editor.json", ContentFile(b'{"transcripts": [{"text": "edited"}]}'))
        current_files.append((transcript.podlove.name, transcript.podlove.read()))
        return {
            "id": "old-cli",
            "state": "succeeded",
            "result": {"artifacts": {"podlove": "p", "dote": "d", "vtt": "v"}},
        }

    client.wait_for_job.side_effect = wait
    mocker.patch.object(
        service,
        "submit_for_audio",
        return_value=TranscriptSubmission(
            job_id="old-cli",
            source_url="https://media.example/synthetic",
            task_ref="cli",
            job_payload={"id": "old-cli", "state": "queued"},
        ),
    )

    publish = mocker.spy(service, "_save_artifacts")
    with pytest.raises(StaleTranscriptAttempt):
        service.generate_for_audio(audio)
    publish.assert_not_called()
    transcript.refresh_from_db()
    assert (transcript.podlove.name == before) is (replacement == "queued")
    assert (transcript.podlove.name, transcript.podlove.read()) == current_files[0]
    assert list(transcript.speaker_mappings.values()) == mapping_state


@pytest.mark.django_db
def test_token_intent_is_consumed(site):
    form = settings_form(VoxhelmSettings(site=site), api_token="first")
    setting = form.save()
    setting.api_token = "second"
    setting.save()
    setting.refresh_from_db()
    assert setting.api_token == "second"


@pytest.mark.django_db
def test_cli_records_submission_failure(audio, mocker):
    service = VoxhelmTranscriptService(client=mocker.Mock())
    mocker.patch.object(service, "submit_for_audio", side_effect=RuntimeError("synthetic failure"))
    with pytest.raises(RuntimeError, match="synthetic failure"):
        service.generate_for_audio(audio)
    generation = TranscriptGeneration.objects.get(audio=audio)
    assert generation.status == generation.Status.FAILED


@pytest.mark.django_db
def test_cli_completion_refuses_attempt_replaced_during_submission(audio, mocker):
    service = VoxhelmTranscriptService(client=mocker.Mock())

    def submit(*args, **kwargs):
        generation = TranscriptGeneration.objects.get(audio=audio)
        generation.queue_submission(
            task_ref="new", voxhelm_job_id="new", source_url="", task_result_id="", site=None, requested_by=None
        )
        return TranscriptSubmission(job_id="old", source_url="", task_ref="old", job_payload={})

    mocker.patch.object(service, "submit_for_audio", side_effect=submit)
    with pytest.raises(StaleTranscriptAttempt):
        service.generate_for_audio(audio)
    generation = TranscriptGeneration.objects.get(audio=audio)
    assert generation.voxhelm_job_id == "new"
    assert generation.status == generation.Status.QUEUED
