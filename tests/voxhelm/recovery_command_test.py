"""Recovery from synthetic corrupt stored transcript artifacts."""

from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from cast.devdata import create_audio, create_transcript
from cast.management.commands import generate_transcripts
from cast.voxhelm import TranscriptGenerationResult, VoxhelmError, service as voxhelm_service


@pytest.fixture(params=["podlove", "dote"])
def corrupt_transcript(request, audio):
    transcript = create_transcript(
        audio=audio,
        podlove={"transcripts": [{"text": "Synthetic"}]},
        vtt="WEBVTT\n\n00:00.000 --> 00:01.000\nSynthetic\n",
        dote={"lines": [{"text": "Synthetic"}]},
    )
    return transcript, getattr(transcript, request.param)


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [b"{broken", b"[]", b"null"])
def test_force_bypasses_old_artifact_completeness(corrupt_transcript, payload, mocker):
    transcript, field = corrupt_transcript
    with field.storage.open(field.name, "wb") as stored:
        stored.write(payload)
    complete = mocker.spy(voxhelm_service, "transcript_complete")
    service = voxhelm_service.VoxhelmTranscriptService(client=mocker.Mock())
    mocker.patch.object(generate_transcripts, "VoxhelmTranscriptService", return_value=service)
    submit = mocker.patch.object(
        service,
        "submit_for_audio",
        return_value=voxhelm_service.TranscriptSubmission("job", "https://media.example/audio", "", {}),
    )
    mocker.patch.object(
        service,
        "complete_audio_job",
        return_value=TranscriptGenerationResult(
            transcript=transcript, created=False, job_id="job", source_url="https://media.example/audio"
        ),
    )
    output = StringIO()

    call_command("generate_transcripts", "--audio-id", str(transcript.audio_id), "--force", stdout=output)

    complete.assert_not_called()
    submit.assert_called_once()
    assert "processed=1 created=0 updated=1 skipped=0 errors=0" in output.getvalue()


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [b"{broken", b"[]", b"null"])
def test_corrupt_artifact_does_not_abandon_batch(corrupt_transcript, payload, mocker):
    transcript, field = corrupt_transcript
    with field.storage.open(field.name, "wb") as stored:
        stored.write(payload)
    other_audio = create_audio()
    other_transcript = create_transcript(audio=other_audio)
    service = voxhelm_service.VoxhelmTranscriptService(client=mocker.Mock())
    mocker.patch.object(generate_transcripts, "VoxhelmTranscriptService", return_value=service)
    submission = voxhelm_service.TranscriptSubmission("job", "https://media.example/audio", "", {})
    submit = mocker.patch.object(
        service, "submit_for_audio", side_effect=[VoxhelmError("synthetic generation failure"), submission]
    )
    mocker.patch.object(
        service,
        "complete_audio_job",
        return_value=TranscriptGenerationResult(other_transcript, False, submission.job_id, submission.source_url),
    )
    output, errors = StringIO(), StringIO()

    with pytest.raises(CommandError, match="1 transcript generations failed"):
        call_command(
            "generate_transcripts",
            "--audio-id",
            str(transcript.audio_id),
            "--audio-id",
            str(other_audio.pk),
            stdout=output,
            stderr=errors,
        )

    assert [call.args[0].pk for call in submit.call_args_list] == [
        transcript.audio_id,
        other_audio.pk,
    ]
    assert f"error audio={transcript.audio_id}: synthetic generation failure" in errors.getvalue()
    assert f"updated audio={other_audio.pk}" in output.getvalue()
    assert "processed=2 created=0 updated=1 skipped=0 errors=1" in output.getvalue()


@pytest.mark.django_db
@pytest.mark.parametrize("force", [False, True])
def test_batch_rechecks_transcript_completed_during_earlier_job(audio, mocker, force):
    from cast.voxhelm import TranscriptSubmission, VoxhelmTranscriptService

    later = create_audio()
    service = VoxhelmTranscriptService(client=mocker.Mock())
    mocker.patch.object(generate_transcripts, "VoxhelmTranscriptService", return_value=service)
    submit = mocker.patch.object(
        service, "submit_for_audio", return_value=TranscriptSubmission("job", "https://media.example/audio", "", {})
    )

    def complete(item, **kwargs):
        if item.pk == audio.pk:
            create_transcript(
                audio=later,
                podlove={"transcripts": [{"text": "Synthetic"}]},
                vtt="WEBVTT\n\n00:00.000 --> 00:01.000\nSynthetic\n",
                dote={"lines": [{"text": "Synthetic"}]},
            )
        transcript, created = service._get_or_create_transcript(audio=item)
        return TranscriptGenerationResult(transcript, created, "job", "https://media.example/audio")

    mocker.patch.object(service, "complete_audio_job", side_effect=complete)
    output = StringIO()
    call_command("generate_transcripts", audio_id=[audio.pk, later.pk], force=force, stdout=output)

    assert [call.args[0].pk for call in submit.call_args_list] == ([audio.pk, later.pk] if force else [audio.pk])
    if not force:
        assert f"skipped audio={later.pk} transcript={later.transcript.pk}" in output.getvalue()
        assert not hasattr(later, "transcript_generation")


@pytest.mark.django_db(transaction=True)
def test_disappeared_middle_target_is_reported_without_abandoning_batch(mocker):
    from wagtail.models import Collection

    from cast.models import Audio, TranscriptGeneration

    if Collection.get_first_root_node() is None:
        Collection.add_root(instance=Collection(name="Synthetic collection"))
    audio, retired, last = (create_audio(unique_filenames=True) for _ in range(3))
    retired_id = retired.pk
    service = voxhelm_service.VoxhelmTranscriptService(client=mocker.Mock())
    mocker.patch.object(generate_transcripts, "VoxhelmTranscriptService", return_value=service)
    submit = mocker.patch.object(
        service,
        "submit_for_audio",
        return_value=voxhelm_service.TranscriptSubmission("job", "https://media.example/audio", "", {}),
    )

    def complete(item, **kwargs):
        if item.pk == audio.pk:
            Audio.objects.filter(pk=retired_id).delete()
        transcript, created = service._get_or_create_transcript(audio=item)
        return TranscriptGenerationResult(transcript, created, "job", "https://media.example/audio")

    mocker.patch.object(service, "complete_audio_job", side_effect=complete)
    output, errors = StringIO(), StringIO()
    with pytest.raises(CommandError, match="1 transcript generations failed"):
        call_command("generate_transcripts", audio_id=[audio.pk, retired_id, last.pk], stdout=output, stderr=errors)

    assert [call.args[0].pk for call in submit.call_args_list] == [audio.pk, last.pk]
    assert f"error audio={retired_id}: Audio {retired_id} disappeared" in errors.getvalue()
    assert f"created audio={last.pk}" in output.getvalue()
    assert TranscriptGeneration.objects.get(audio=last).status == TranscriptGeneration.Status.SUCCEEDED


@pytest.mark.django_db
def test_unrelated_claim_integrity_error_is_preserved(audio, mocker):
    from django.db import IntegrityError

    failure = IntegrityError("synthetic claim constraint")
    service = voxhelm_service.VoxhelmTranscriptService(client=mocker.Mock())
    mocker.patch.object(generate_transcripts, "VoxhelmTranscriptService", return_value=service)
    mocker.patch("django.db.models.QuerySet.get_or_create", side_effect=failure)
    with pytest.raises(IntegrityError) as caught:
        call_command("generate_transcripts", audio_id=[audio.pk])
    assert caught.value is failure
