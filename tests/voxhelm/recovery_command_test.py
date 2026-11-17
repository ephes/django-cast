"""Recovery from synthetic corrupt stored transcript artifacts."""

from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from cast.devdata import create_audio, create_transcript
from cast.management.commands import generate_transcripts
from cast.voxhelm import TranscriptGenerationResult, VoxhelmError


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
    complete = mocker.spy(generate_transcripts, "transcript_complete")
    service = mocker.patch("cast.management.commands.generate_transcripts.VoxhelmTranscriptService").return_value
    service.generate_for_audio.return_value = TranscriptGenerationResult(
        transcript=transcript, created=False, job_id="synthetic-job", source_url="https://media.example/audio.m4a"
    )
    output = StringIO()

    call_command("generate_transcripts", "--audio-id", str(transcript.audio_id), "--force", stdout=output)

    complete.assert_not_called()
    service.generate_for_audio.assert_called_once()
    assert "processed=1 created=0 updated=1 skipped=0 errors=0" in output.getvalue()


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [b"{broken", b"[]", b"null"])
def test_corrupt_artifact_does_not_abandon_batch(corrupt_transcript, payload, mocker):
    transcript, field = corrupt_transcript
    with field.storage.open(field.name, "wb") as stored:
        stored.write(payload)
    other_audio = create_audio()
    other_transcript = create_transcript(audio=other_audio)
    service = mocker.patch("cast.management.commands.generate_transcripts.VoxhelmTranscriptService").return_value
    service.generate_for_audio.side_effect = [
        VoxhelmError("synthetic generation failure"),
        TranscriptGenerationResult(
            transcript=other_transcript,
            created=False,
            job_id="synthetic-job",
            source_url="https://media.example/audio.m4a",
        ),
    ]
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

    assert [call.args[0].pk for call in service.generate_for_audio.call_args_list] == [
        transcript.audio_id,
        other_audio.pk,
    ]
    assert f"error audio={transcript.audio_id}: synthetic generation failure" in errors.getvalue()
    assert f"updated audio={other_audio.pk}" in output.getvalue()
    assert "processed=2 created=0 updated=1 skipped=0 errors=1" in output.getvalue()
