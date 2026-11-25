"""Synthetic stale-form and synchronous generation interleavings."""

import re
from io import StringIO

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.forms import modelform_factory
from django.test import TestCase
from django.urls import reverse

from cast.models import TranscriptGeneration, VoxhelmSettings
from cast.models.voxhelm_settings import TokenInput, VoxhelmSettingsForm, api_token_version, ordinary_settings_version
from cast.voxhelm import TranscriptSubmission, VoxhelmTranscriptService
from cast.voxhelm.service import StaleTranscriptAttempt, TranscriptGenerationActive
from tests.transcripts.known_speaker_apply_helpers import make_transcript
from tests.voxhelm.tasks_status_helpers import VALID_DOTE_ARTIFACT, VALID_PODLOVE_ARTIFACT, VALID_VTT_ARTIFACT


def settings_form(instance, **data):
    form_class = modelform_factory(VoxhelmSettings, form=VoxhelmSettingsForm, fields=["api_token", "language"])
    form = form_class(
        data={"api_token": "", "language": "de", "settings_version": ordinary_settings_version(instance), **data},
        instance=instance,
    )
    assert form.is_valid(), form.errors
    return form


@pytest.mark.django_db
@pytest.mark.parametrize("current_token", ["rotated-synthetic", ""])
@pytest.mark.parametrize("commit", [True, False])
def test_blank_form_preserves_token_at_save(site, current_token, commit):
    setting = VoxhelmSettings.objects.create(site=site, api_token="old-synthetic")
    stale = settings_form(VoxhelmSettings.objects.get(pk=setting.pk))
    settings_form(setting, api_token=current_token, clear_api_token=not current_token, language="").save()
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


def queued_generation(audio):
    generation, _ = TranscriptGeneration.objects.get_or_create(audio=audio, defaults={"task_ref": ""})
    generation.queue_submission(
        task_ref="admin", voxhelm_job_id="admin-job", source_url="", task_result_id="", site=None, requested_by=None
    )
    return TranscriptGeneration.objects.get(pk=generation.pk)


@pytest.mark.django_db
def test_cli_refuses_to_preempt_active_generation(audio, mocker):
    queued = queued_generation(audio)
    service = VoxhelmTranscriptService(client=mocker.Mock())
    submit = mocker.patch.object(service, "submit_for_audio")
    with pytest.raises(TranscriptGenerationActive):
        service.generate_for_audio(audio)
    submit.assert_not_called()
    generation = TranscriptGeneration.objects.get(pk=queued.pk)
    assert (generation.attempt_id, generation.status, generation.voxhelm_job_id) == (
        queued.attempt_id,
        TranscriptGeneration.Status.QUEUED,
        "admin-job",
    )


@pytest.mark.django_db
def test_generate_transcripts_command_skips_active_generation(audio, mocker, settings):
    settings.CAST_VOXHELM_API_BASE = "https://voxhelm.example"
    settings.CAST_VOXHELM_API_KEY = "synthetic"
    queued_generation(audio)
    submit = mocker.patch.object(VoxhelmTranscriptService, "submit_for_audio")
    stdout = StringIO()
    call_command("generate_transcripts", "--audio-id", str(audio.pk), "--force", stdout=stdout)
    submit.assert_not_called()
    assert f"skipped audio={audio.pk}: Transcript generation is already queued or running" in stdout.getvalue()
    assert "skipped=1 errors=0" in stdout.getvalue()


@pytest.mark.django_db
def test_cli_interrupt_marks_generation_failed(audio, mocker):
    service = VoxhelmTranscriptService(client=mocker.Mock())
    mocker.patch.object(service, "submit_for_audio", side_effect=KeyboardInterrupt)
    with pytest.raises(KeyboardInterrupt):
        service.generate_for_audio(audio)
    assert TranscriptGeneration.objects.get(audio=audio).status == TranscriptGeneration.Status.FAILED


@pytest.mark.django_db
@pytest.mark.parametrize("clear", [True, False])
def test_form_reports_token_changed_after_render(site, clear):
    setting = VoxhelmSettings.objects.create(site=site, api_token="old-synthetic")
    rendered = api_token_version("old-synthetic")
    VoxhelmSettings.objects.filter(pk=setting.pk).update(api_token="rotated")
    form_class = modelform_factory(VoxhelmSettings, form=VoxhelmSettingsForm, fields=["api_token", "language"])
    data = {
        "api_token": "" if clear else "replacement",
        "language": "de",
        "api_token_version": rendered,
        "settings_version": ordinary_settings_version(setting),
    }
    if clear:
        data["clear_api_token"] = "on"
    form = form_class(data=data, instance=VoxhelmSettings.objects.get(pk=setting.pk))
    assert not form.is_valid()
    assert "changed" in str(form.errors["api_token"])


@pytest.mark.django_db
def test_settings_edit_view_refuses_stale_token_replacement(admin_client, site):
    setting = VoxhelmSettings.objects.create(site=site, api_token="old-synthetic")
    edit_url = reverse("wagtailsettings:edit", args=("cast", "voxhelmsettings", site.pk))
    content = admin_client.get(edit_url).content.decode()
    # Build the POST from what the browser submits: exactly one fingerprint input.
    versions = re.findall(r'<input[^>]*name="api_token_version"[^>]*>', content)
    assert len(versions) == 1, versions
    rendered = re.search(r'value="([^"]*)"', versions[0]).group(1)
    assert rendered == api_token_version("old-synthetic")
    assert "old-synthetic" not in content
    # Another administrator rotates the token after the page was opened.
    VoxhelmSettings.objects.filter(pk=setting.pk).update(api_token="rotated")
    post = {
        "api_token_version": rendered,
        "settings_version": ordinary_settings_version(setting),
        "model": "",
        "language": "",
        "diarization_enabled": "unknown",
    }

    response = admin_client.post(edit_url, {**post, "api_token": "replacement"})

    assert response.status_code == 200
    assert "Reload settings before replacing or removing it" in response.content.decode()
    setting.refresh_from_db()
    assert setting.api_token == "rotated"

    with TestCase.captureOnCommitCallbacks(execute=True):
        response = admin_client.post(edit_url, {**post, "api_token": "", "language": "de"}, follow=True)
    assert response.status_code == 200
    setting.refresh_from_db()
    assert (setting.api_token, setting.language) == ("rotated", "de")


@pytest.mark.django_db
@pytest.mark.parametrize("existing", [True, False])
def test_settings_edit_view_refuses_stale_ordinary_fields(admin_client, site, existing):
    if existing:
        VoxhelmSettings.objects.create(site=site, api_token="old-synthetic", language="fr")
    edit_url = reverse("wagtailsettings:edit", args=("cast", "voxhelmsettings", site.pk))

    def snapshot():
        response = admin_client.get(edit_url)
        form = response.context["form"]
        versions = re.findall(r'<input[^>]*name="settings_version"[^>]*>', response.content.decode())
        assert len(versions) == 1, versions
        version = re.search(r'value="([^"]*)"', versions[0]).group(1)
        return {"language": form["language"].value(), "settings_version": version}

    stale = snapshot()
    fresh = snapshot()
    with TestCase.captureOnCommitCallbacks(execute=True):
        updated = admin_client.post(edit_url, {**fresh, "language": "de", "diarization_enabled": "true"})
    assert updated.status_code == 302

    response = admin_client.post(edit_url, {**stale, "api_token": "replacement"})
    assert response.status_code == 200
    assert "Reload settings before saving" in response.content.decode()
    assert response.context["form"]["settings_version"].value() == stale["settings_version"]
    setting = VoxhelmSettings.objects.get(site=site)
    assert setting.language == "de"
    assert setting.diarization_enabled is True
    assert setting.api_token == ("old-synthetic" if existing else "")


@pytest.mark.django_db
@pytest.mark.parametrize("snapshot_data", [{}, {"settings_version": "0" * 64}, {"settings_version": "\x00"}])
def test_settings_edit_view_refuses_missing_or_invalid_snapshot(admin_client, site, snapshot_data):
    setting = VoxhelmSettings.objects.create(site=site, language="fr")
    edit_url = reverse("wagtailsettings:edit", args=("cast", "voxhelmsettings", site.pk))
    response = admin_client.post(edit_url, {"language": "de", **snapshot_data})
    assert response.status_code == 200
    assert "Reload settings before saving" in response.content.decode()
    setting.refresh_from_db()
    assert setting.language == "fr"


@pytest.mark.django_db
def test_ordinary_fields_are_rechecked_at_save(site):
    setting = VoxhelmSettings.objects.create(site=site, language="fr", api_token="old-synthetic")
    stale = settings_form(setting, api_token="replacement", language="fr")
    pending = stale.save(commit=False)
    VoxhelmSettings.objects.filter(pk=setting.pk).update(language="de")
    with pytest.raises(ValidationError, match="Reload settings before saving"):
        pending.save()
    setting.refresh_from_db()
    assert (setting.language, setting.api_token) == ("de", "old-synthetic")


def test_token_input_without_form_renders_only_the_password_field():
    html = TokenInput().render("api_token", "secret-synthetic")
    assert 'type="password"' in html
    assert "hidden" not in html
    assert "secret-synthetic" not in html
