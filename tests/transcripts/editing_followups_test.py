"""Follow-ups from the integration review and admin walk-through of the transcript editing UX."""

import json

import pytest
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from cast.transcripts import services
from tests.known_speaker_apply_test import make_transcript
from tests.transcripts.remaining_ux_test import passage_transcript

pytestmark = pytest.mark.django_db


def test_duplicate_start_times_index_as_empty_text_instead_of_failing(admin_client, episode):
    transcript = make_transcript(
        episode.podcast_audio, podlove={"transcripts": [{"start_ms": 0, "text": "A"}, {"start_ms": 0, "text": "B"}]}
    )
    assert transcript.plain_text == ""
    duplicate = b'{"transcripts": [{"start_ms": 0, "text": "A"}, {"start_ms": 0, "text": "B"}]}'
    response = admin_client.post(
        reverse("cast-transcript:edit", args=(transcript.pk,)),
        {
            "audio": episode.podcast_audio_id,
            "collection": transcript.collection_id,
            "podlove": SimpleUploadedFile("dup.json", duplicate),
        },
    )
    assert response.status_code == 302


def test_replacing_a_transcript_whose_stored_file_is_missing(admin_user, episode):
    from cast.forms import TranscriptForm
    from cast.transcripts.versions import read_previous

    transcript = passage_transcript(episode)
    transcript.podlove.storage.delete(transcript.podlove.name)
    form = TranscriptForm(
        {"audio": episode.podcast_audio_id, "collection": transcript.collection_id},
        {"podlove": SimpleUploadedFile("new.json", b'{"transcripts": [{"start_ms": 0, "text": "New"}]}')},
        instance=transcript,
        user=admin_user,
    )
    assert form.is_valid(), form.errors
    form.save()
    transcript.refresh_from_db()
    assert transcript.plain_text == "New"
    kept = read_previous(transcript)["files"]
    assert "podlove" not in kept and "dote" in kept


def test_inline_correction_folds_whitespace_in_every_format(admin_client, episode):
    transcript = passage_transcript(episode)
    url = reverse("cast-transcript:preview", args=(transcript.pk,))
    response = admin_client.post(
        url,
        {
            "action": "correct-text",
            "start_ms": 0,
            "text": "  Two\nlines  here ",
            "artifact_revision": services.artifact_revision(transcript),
        },
    )
    assert response.status_code == 200
    assert response.json()["text"] == "Two lines here"
    transcript.refresh_from_db()
    assert transcript.podlove_data["transcripts"][0]["text"] == "Two lines here"
    assert transcript.dote_data["lines"][0]["text"] == "Two lines here"
    assert "Two lines here" in transcript._load_text_file("vtt")


def test_preview_errors_are_plain_sentences(admin_client, episode):
    transcript = passage_transcript(episode)
    url = reverse("cast-transcript:preview", args=(transcript.pk,))
    revision = services.artifact_revision(transcript)
    empty = admin_client.post(
        url, {"action": "correct-text", "start_ms": 0, "text": " ", "artifact_revision": revision}
    )
    assert empty.status_code == 400
    assert empty.content.decode() == "Enter passage text (at most 100,000 characters)."
    broken = admin_client.post(url, {"action": "correct-text", "start_ms": "x", "artifact_revision": revision})
    assert broken.status_code == 400
    assert broken.content.decode() == "Reload the transcript and try again."


def test_preview_explains_inline_editing_and_escapes_script_strings(admin_client, episode):
    transcript = passage_transcript(episode)
    content = admin_client.get(reverse("cast-transcript:preview", args=(transcript.pk,))).content.decode()
    assert "Click a passage to correct its text." in content
    assert "1 passage without a name" in content
    assert 'saving: "Saving…"' in content


def test_restore_button_shows_a_formatted_date(admin_client, episode):
    transcript = passage_transcript(episode)
    payload = {
        "version": 1,
        "files": {},
        "mappings": [],
        "source_fingerprint": "",
        "saved_at": "2026-11-15T07:05:00+00:00",
    }
    transcript.previous_version.save("previous.json", ContentFile(json.dumps(payload).encode()))
    content = admin_client.get(reverse("cast-transcript:edit", args=(transcript.pk,))).content.decode()
    assert "Restore the version from" in content
    assert "2026-11-15T07:05" not in content
    assert transcript.previous_version_date.year == 2026


def test_regenerate_confirmation_mentions_restore_inside_the_page(admin_client, episode, settings):
    settings.CAST_VOXHELM_API_BASE = "https://voxhelm.example"
    settings.CAST_VOXHELM_API_KEY = "secret"
    passage_transcript(episode)
    content = admin_client.get(reverse("cast-voxhelm:generate_episode", args=(episode.pk,))).content.decode()
    assert "There is no restore option" not in content
    assert "you can restore it on the transcript page" in content
    assert "Spelling corrections:" in content


def test_audio_editor_does_not_put_csrf_token_into_a_get_form(admin_client, episode, settings):
    settings.CAST_VOXHELM_API_BASE = "https://voxhelm.example"
    settings.CAST_VOXHELM_API_KEY = "secret"
    audio = episode.podcast_audio
    passage_transcript(episode)
    content = admin_client.get(reverse("castaudio:edit", args=(audio.pk,))).content.decode()
    form = content[content.index('class="cast-transcript-actions__form"') :]
    form = form[: form.index("</form>")]
    assert "csrfmiddlewaretoken" not in form


def test_editor_opens_files_section_for_upload_errors(admin_client, episode):
    transcript = passage_transcript(episode)
    response = admin_client.post(
        reverse("cast-transcript:edit", args=(transcript.pk,)),
        {
            "audio": episode.podcast_audio_id,
            "collection": transcript.collection_id,
            "podlove": SimpleUploadedFile("wrong.json", b"WEBVTT\n"),
        },
    )
    assert response.status_code == 200
    assert '<details id="files" open>' in response.content.decode()


def test_preview_reports_artifact_errors_verbatim(admin_client, episode, mocker):
    from cast.transcripts.parsing import TranscriptArtifactError

    transcript = passage_transcript(episode)
    mocker.patch("cast.models.Transcript.correct_passage_text", side_effect=TranscriptArtifactError("Bad file."))
    response = admin_client.post(
        reverse("cast-transcript:preview", args=(transcript.pk,)),
        {
            "action": "correct-text",
            "start_ms": 0,
            "text": "x",
            "artifact_revision": services.artifact_revision(transcript),
        },
    )
    assert response.status_code == 400
    assert response.content.decode() == "Bad file."
