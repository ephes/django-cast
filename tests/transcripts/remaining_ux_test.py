"""Editor workflow regression tests for the remaining transcript slices."""

import pytest
from django.urls import reverse

from cast.models import Contributor, EpisodeContributor
from cast.transcripts import editing
from tests.known_speaker_apply_test import make_transcript

pytestmark = pytest.mark.django_db


def named_episode(episode):
    contributor = Contributor.objects.create(display_name="Host", slug="host")
    EpisodeContributor.objects.create(episode=episode, contributor=contributor, role="host")
    episode.save_revision()
    return contributor


def test_mapped_voice_can_be_saved_as_sample(admin_client, episode):
    contributor = named_episode(episode)
    transcript = make_transcript(
        episode.podcast_audio,
        podlove={
            "transcripts": [
                {"speaker": "Speaker 1", "start_ms": 0, "end_ms": 20000, "text": "An extended voice sample."}
            ]
        },
    )
    transcript.sync_speaker_mappings()
    mapping = transcript.speaker_mappings.get()
    mapping.contributor = contributor
    mapping.review_state = "approved"
    mapping.save()
    context = editing.get_speaker_mapping_context(transcript)
    assert (
        editing.resolve_voice_reference_contributor(
            "Speaker 1", context["contributor_assignments"], context["speaker_mappings"]
        )
        == contributor
    )
    candidate = transcript.get_voice_reference_candidates()[0]
    reference, created = editing.create_voice_reference_from_candidate(
        transcript, context, candidate, status="pending", consent_confirmed=False
    )
    assert created and reference.contributor == contributor
    content = admin_client.get(reverse("cast-transcript:edit", args=(transcript.pk,))).content.decode()
    assert (
        content.index("Speakers</h2>")
        < content.index("Voice samples for next time")
        < content.index(">Files</summary>")
    )
    assert "Existing sample" in content
    assert "raw Podlove" not in content and "margin " not in content and "bulk action" not in content


def test_uploaded_public_file_detaches_speaker_suggestions(admin_user, episode):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from cast.forms import TranscriptForm

    transcript = make_transcript(episode.podcast_audio, podlove={"transcripts": []}, speakers={"segments": []})
    form = TranscriptForm(
        {"audio": episode.podcast_audio_id, "collection": transcript.collection_id},
        {"podlove": SimpleUploadedFile("new.json", b'{"transcripts": []}')},
        instance=transcript,
        user=admin_user,
    )
    assert form.is_valid(), form.errors
    form.save()
    transcript.refresh_from_db()
    assert not transcript.speakers


def passage_transcript(episode, *, speakers=None):
    return make_transcript(
        episode.podcast_audio,
        podlove={"transcripts": [{"speaker": "Speaker 1", "start_ms": 0, "end_ms": 20000, "text": "Original"}]},
        dote={
            "lines": [
                {
                    "startTime": "00:00:00,000",
                    "endTime": "00:00:20,000",
                    "speakerDesignation": "Speaker 1",
                    "text": "Original",
                }
            ]
        },
        vtt="WEBVTT\n\n00:00:00.000 --> 00:00:20.000\n<v Speaker 1>Original</v>\n",
        speakers=speakers,
    )


def test_preview_and_one_passage_speaker_change(admin_client, episode):
    from cast.transcripts import services

    named_episode(episode)
    transcript = passage_transcript(episode, speakers={"segments": [{"start": 0, "speaker_uncertain": True}]})
    url = reverse("cast-transcript:preview", args=(transcript.pk,))
    response = admin_client.get(url)
    assert response.status_code == 200
    assert "1 passage without a name" in response.content.decode()
    assert (
        admin_client.post(
            url, {"start_ms": 0, "speaker": "Host", "artifact_revision": services.artifact_revision(transcript)}
        ).status_code
        == 302
    )
    transcript.refresh_from_db()
    assert transcript.podlove_data["transcripts"][0]["speaker"] == "Host"
    assert transcript.dote_data["lines"][0]["speakerDesignation"] == "Host"
    assert "<v Host>" in transcript._load_text_file("vtt")
    assert transcript.speakers_data["segments"][0]["editor_decision"]["speaker"] == "Host"
    assert "0 passages without a name" in admin_client.get(url).content.decode()
    assert admin_client.post(url, {"start_ms": 0, "speaker": "", "artifact_revision": "stale"}).status_code == 409
    assert (
        admin_client.post(
            url, {"start_ms": 0, "speaker": "Intruder", "artifact_revision": services.artifact_revision(transcript)}
        ).status_code
        == 400
    )


def test_inline_text_correction_updates_all_formats_and_survives_glossary(admin_client, episode, mocker):
    from cast.transcripts import corrections, services

    transcript = passage_transcript(episode)
    url = reverse("cast-transcript:preview", args=(transcript.pk,))
    backend = mocker.Mock()
    mocker.patch("cast.views.transcript.get_search_backends", return_value=[backend])
    response = admin_client.post(
        url,
        {
            "action": "correct-text",
            "start_ms": 0,
            "text": "Corrected <words>",
            "artifact_revision": services.artifact_revision(transcript),
        },
    )
    assert response.status_code == 200, response.content
    transcript.refresh_from_db()
    assert transcript.plain_text == "Corrected <words>"
    assert transcript.dote_data["lines"][0]["text"] == "Corrected <words>"
    assert "Corrected &lt;words&gt;" in transcript._load_text_file("vtt")
    backend.add.assert_called_once()
    corrections.refresh_transcript_corrections(transcript, episode=episode)
    assert transcript.plain_text == "Corrected <words>"
    assert transcript.corrections_data["manual_texts"] == {"0": "Corrected <words>"}
    assert (
        admin_client.post(
            url, {"action": "correct-text", "start_ms": 0, "text": "stale", "artifact_revision": "old"}
        ).status_code
        == 409
    )


def test_preview_paging_and_permission(admin_client, client, episode):
    transcript = make_transcript(
        episode.podcast_audio, podlove={"transcripts": [{"start_ms": i * 1000, "text": str(i)} for i in range(201)]}
    )
    url = reverse("cast-transcript:preview", args=(transcript.pk,))
    from django.test import Client

    assert Client().get(url).status_code in (302, 404)
    response = admin_client.get(url)
    assert len(response.context["passage_page"]) == 200
    assert len(admin_client.get(url + "?page=2").context["passage_page"]) == 1


def test_upload_requires_a_file_and_explains_wrong_fields(admin_user, audio):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from wagtail.models import Collection

    from cast.forms import TranscriptForm

    data = {"audio": audio.pk, "collection": Collection.get_first_root_node().pk}
    assert "Upload at least one" in str(TranscriptForm(data, user=admin_user).errors)
    for field, payload, destination in [
        ("podlove", b"WEBVTT\n", "WebVTT Transcript"),
        ("podlove", b'{"lines": []}', "DOTe Transcript"),
        ("dote", b'{"transcripts": []}', "Podlove Transcript"),
        ("vtt", b'{"transcripts": []}', "Podlove Transcript"),
        ("vtt", b'{"lines": []}', "DOTe Transcript"),
    ]:
        form = TranscriptForm(data, {field: SimpleUploadedFile("wrong.txt", payload)}, user=admin_user)
        assert destination in str(form.errors)


def test_upload_audio_choices_duplicates_and_missing_format_notice(admin_client, admin_user, episode):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from wagtail.models import Collection

    from cast.forms import TranscriptForm

    audio = episode.podcast_audio
    form = TranscriptForm(user=admin_user)
    assert episode.title in form.fields["audio"].label_from_instance(audio)
    response = admin_client.post(
        reverse("cast-transcript:add"),
        {
            "audio": audio.pk,
            "collection": Collection.get_first_root_node().pk,
            "vtt": SimpleUploadedFile("t.vtt", b"WEBVTT\n"),
        },
        follow=True,
    )
    assert response.status_code == 200
    assert "No transcript yet for: web player" in response.content.decode()
    form = TranscriptForm(user=admin_user)
    assert audio not in form.fields["audio"].queryset
    response = admin_client.post(
        reverse("cast-transcript:add"), {"audio": audio.pk, "collection": Collection.get_first_root_node().pk}
    )
    assert "Edit the existing transcript" in response.content.decode()


def test_previous_version_restores_text_and_mapping_and_swaps(
    admin_client, episode, django_capture_on_commit_callbacks
):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from cast.forms import TranscriptForm
    from cast.transcripts import services
    from cast.transcripts.versions import read_previous

    contributor = named_episode(episode)
    transcript = passage_transcript(episode, speakers={"segments": [{"start": 0}]})
    transcript.sync_speaker_mappings()
    mapping = transcript.speaker_mappings.get()
    mapping.contributor = contributor
    mapping.review_state = "approved"
    mapping.save()
    transcript.correct_passage_text(0, "Manual correction")
    form = TranscriptForm(
        {"audio": episode.podcast_audio_id, "collection": transcript.collection_id},
        {"podlove": SimpleUploadedFile("new.json", b'{"transcripts": [{"start_ms": 0, "text": "New"}]}')},
        instance=transcript,
    )
    assert form.is_valid(), form.errors
    form.save()
    assert transcript.plain_text == "New"
    assert read_previous(transcript)["files"]["corrections"]
    with pytest.raises(ValueError):
        _ = transcript.previous_version.url
    url = reverse("cast-transcript:edit", args=(transcript.pk,))
    assert admin_client.post(url, {"action": "restore-version", "artifact_revision": "stale"}).status_code == 409
    assert (
        admin_client.post(
            url, {"action": "restore-version", "artifact_revision": services.artifact_revision(transcript)}
        ).status_code
        == 302
    )
    transcript.refresh_from_db()
    assert transcript.plain_text == "Manual correction"
    assert transcript.speakers and transcript.corrections
    assert transcript.speaker_mappings.get().contributor == contributor
    assert (
        admin_client.post(
            url, {"action": "restore-version", "artifact_revision": services.artifact_revision(transcript)}
        ).status_code
        == 302
    )
    transcript.refresh_from_db()
    assert transcript.plain_text == "New"
    assert not transcript.speakers and not transcript.corrections
    with django_capture_on_commit_callbacks(execute=True):
        previous = transcript.previous_version.name
        storage = transcript.previous_version.storage
        transcript.delete()
    assert not storage.exists(previous)


def test_passage_edits_validate_identity_and_preserve_earlier_edits(episode):
    from django.core.exceptions import ValidationError

    from cast.transcripts.passages import get_passages

    transcript = passage_transcript(episode, speakers={"segments": [{"start": 0}, {"start": 99}]})
    transcript.change_passage_speaker(0, "")
    assert not transcript.podlove_data["transcripts"][0].get("speaker")
    assert transcript.speakers_data["segments"][0]["editor_decision"]["action"] == "reject"
    transcript.correct_passage_text(0, "First")
    transcript.correct_passage_text(0, "Second")
    assert transcript.plain_text == "Second"
    for call in (
        lambda: transcript.change_passage_speaker(999, "Host"),
        lambda: transcript.correct_passage_text(999, "Missing"),
        lambda: transcript.correct_passage_text(0, ""),
        lambda: transcript.correct_passage_text(0, "x" * 100001),
    ):
        with pytest.raises(ValidationError):
            call()
    transcript.podlove = ""
    transcript.vtt = ""
    transcript.save(preserve_source_fingerprint=True, update_fields=["podlove", "vtt"])
    assert get_passages(transcript)[0]["text"] == "Second"
    transcript.change_passage_speaker(0, "Host")
    transcript.change_passage_speaker(0, "")


def test_vtt_only_preview_and_edit(admin_client, episode):
    from cast.transcripts.passages import get_passages

    transcript = make_transcript(
        episode.podcast_audio,
        vtt="WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n<v Host>Hello</v>\n\n00:00:02.000 --> 00:00:04.000\nPlain\n",
    )
    assert [row["text"] for row in get_passages(transcript)] == ["Hello", "Plain"]
    assert admin_client.get(reverse("cast-transcript:preview", args=(transcript.pk,))).status_code == 200
    transcript.correct_passage_text(0, "Corrected")
    assert get_passages(transcript)[0]["text"] == "Corrected"


def test_preview_conflicts_and_error_responses(admin_client, episode, mocker):
    from django.core.exceptions import ValidationError

    from cast.transcripts import services

    transcript = passage_transcript(episode)
    url = reverse("cast-transcript:preview", args=(transcript.pk,))
    data = {"start_ms": 0, "speaker": "", "artifact_revision": services.artifact_revision(transcript)}
    mocker.patch(
        "cast.models.Transcript.change_passage_speaker", side_effect=services.TranscriptEditConflict("changed")
    )
    assert admin_client.post(url, data).status_code == 409
    mocker.patch("cast.transcripts.passages.get_passages", side_effect=ValidationError("bad timestamps"))
    assert admin_client.get(url).status_code == 400


def test_failed_speaker_write_preserves_files(episode, mocker):
    from cast.transcripts import services

    transcript = passage_transcript(episode)
    before = services.artifact_revision(transcript)
    mocker.patch(
        "cast.transcripts.services.save_editor_artifacts", side_effect=services.TranscriptEditConflict("changed")
    )
    with pytest.raises(services.TranscriptEditConflict):
        transcript.change_passage_speaker(0, "Host")
    transcript.refresh_from_db()
    assert services.artifact_revision(transcript) == before
    assert transcript.plain_text == "Original"


def test_restore_missing_or_corrupt_version_is_safe(admin_client, episode, mocker):
    import json

    from django.core.exceptions import ValidationError
    from django.core.files.base import ContentFile

    from cast.transcripts import services
    from cast.transcripts.versions import read_previous

    transcript = passage_transcript(episode)
    assert transcript.previous_version_date is None
    url = reverse("cast-transcript:edit", args=(transcript.pk,))
    assert (
        admin_client.post(
            url, {"action": "restore-version", "artifact_revision": services.artifact_revision(transcript)}
        ).status_code
        == 400
    )
    for payload in (
        {"version": 2, "files": {}, "mappings": []},
        {"version": 1, "files": {"unknown": {}}, "mappings": []},
        {"version": 1, "files": {"podlove": {"name": 1}}, "mappings": []},
    ):
        transcript.previous_version.save(
            "broken.json",
            ContentFile(json.dumps({"source_fingerprint": "", "saved_at": "today", **payload}).encode()),
            save=False,
        )
        with pytest.raises(ValidationError):
            read_previous(transcript)
    mocker.patch("cast.transcripts.versions.restore", side_effect=services.TranscriptEditConflict("changed"))
    assert (
        admin_client.post(
            url, {"action": "restore-version", "artifact_revision": services.artifact_revision(transcript)}
        ).status_code
        == 409
    )


def test_restore_failure_rolls_back_and_missing_contributor_needs_review(episode, mocker):
    from cast.transcripts import services
    from cast.transcripts.versions import replacing, restore

    contributor = named_episode(episode)
    transcript = passage_transcript(episode)
    transcript.sync_speaker_mappings()
    mapping = transcript.speaker_mappings.get()
    mapping.contributor = contributor
    mapping.review_state = "approved"
    mapping.save()
    with replacing(transcript):
        transcript.correct_passage_text(0, "Current")
    episode.contributor_assignments.all().delete()
    contributor.delete()
    restore(transcript)
    assert transcript.speaker_mappings.get().review_state == "stale"
    before = services.artifact_revision(transcript)
    mocker.patch(
        "cast.transcripts.services.save_editor_artifacts", side_effect=services.TranscriptEditConflict("changed")
    )
    with pytest.raises(services.TranscriptEditConflict):
        restore(transcript)
    transcript.refresh_from_db()
    assert services.artifact_revision(transcript) == before


def test_duplicate_passage_times_and_unsupported_vtt_are_rejected(episode):
    from django.core.exceptions import ValidationError

    from cast.transcripts.passages import get_passages

    transcript = make_transcript(episode.podcast_audio, podlove={"transcripts": [{"start_ms": 0}, {"start_ms": 0}]})
    with pytest.raises(ValidationError):
        get_passages(transcript)
    transcript.podlove = ""
    from django.core.files.base import ContentFile

    transcript.vtt.save(
        "bad.vtt",
        ContentFile(b"WEBVTT\n\n999999999999999999999:00:00.000 --> 999999999999999999999:00:01.000\nUnkeyed\n"),
        save=False,
    )
    with pytest.raises(ValidationError):
        get_passages(transcript)


def test_manual_correction_refuses_partial_format_updates(episode):
    from django.core.exceptions import ValidationError
    from django.core.files.base import ContentFile

    from cast.transcripts import services

    transcript = passage_transcript(episode)
    transcript.vtt.save("styled.vtt", ContentFile(b"WEBVTT\n\n00:00:00.000 --> 00:00:20.000\n<b>Styled</b>\n"))
    before = services.artifact_revision(transcript)
    with pytest.raises(ValidationError, match="formatting"):
        transcript.correct_passage_text(0, "New")
    assert transcript.plain_text == "Original"
    assert services.artifact_revision(transcript) == before
    transcript.vtt.save("wrong.vtt", ContentFile(b"WEBVTT\n\n00:00:01.000 --> 00:00:20.000\nWrong time\n"))
    with pytest.raises(ValidationError, match="timestamps"):
        transcript.correct_passage_text(0, "New")
    transcript.vtt = ""
    transcript.dote.save("wrong.json", ContentFile(b'{"lines": [{"startTime": "00:00:01,000", "text": "Wrong"}]}'))
    with pytest.raises(ValidationError, match="timestamps"):
        transcript.correct_passage_text(0, "New")


def test_preview_without_episode_and_unchanged_commit_false(admin_client, audio):
    from cast.forms import TranscriptForm

    transcript = make_transcript(audio, podlove={"transcripts": []})
    response = admin_client.get(reverse("cast-transcript:preview", args=(transcript.pk,)))
    assert response.status_code == 200
    assert response.context["episode_id"] == ""
    form = TranscriptForm({"audio": audio.pk, "collection": transcript.collection_id}, instance=transcript)
    assert form.is_valid()
    assert form.save(commit=False).pk == transcript.pk


def test_unknown_json_upload_explains_required_structure(admin_user, audio):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from wagtail.models import Collection

    from cast.forms import TranscriptForm

    form = TranscriptForm(
        {"audio": audio.pk, "collection": Collection.get_first_root_node().pk},
        {"podlove": SimpleUploadedFile("empty.json", b"{}")},
        user=admin_user,
    )
    assert "top-level" in str(form.errors)


def test_text_correction_refreshes_search_index(admin_client, episode):
    from wagtail.search.backends import get_search_backend

    from cast.models import Transcript
    from cast.transcripts import services

    transcript = passage_transcript(episode)
    backend = get_search_backend()
    backend.add(transcript)
    assert transcript.pk in [row.pk for row in backend.search("Original", Transcript)]
    response = admin_client.post(
        reverse("cast-transcript:preview", args=(transcript.pk,)),
        {
            "action": "correct-text",
            "start_ms": 0,
            "text": "Unmistakableword",
            "artifact_revision": services.artifact_revision(transcript),
        },
    )
    assert response.status_code == 200
    assert transcript.pk in [row.pk for row in backend.search("Unmistakableword", Transcript)]
    assert transcript.pk not in [row.pk for row in backend.search("Original", Transcript)]


def test_previous_version_rejects_incomplete_metadata(episode):
    import json

    from django.core.exceptions import ValidationError
    from django.core.files.base import ContentFile

    from cast.transcripts.versions import read_previous

    transcript = passage_transcript(episode)
    for metadata in ({"source_fingerprint": None}, {"mappings": [{}]}):
        payload = {
            "version": 1,
            "files": {},
            "mappings": [],
            "saved_at": "today",
            "source_fingerprint": "",
            **metadata,
        }
        transcript.previous_version.save("broken.json", ContentFile(json.dumps(payload).encode()), save=False)
        with pytest.raises(ValidationError):
            read_previous(transcript)


def test_standard_podlove_timestamp_upload_can_be_previewed_and_corrected(admin_client, episode):
    transcript = make_transcript(
        episode.podcast_audio,
        podlove={
            "transcripts": [
                {"start": "00:00:01.250", "end": "00:00:03.000", "text": "Uploaded words", "speaker": "Speaker 1"}
            ]
        },
    )
    assert transcript.plain_text == "Uploaded words"
    assert admin_client.get(reverse("cast-transcript:preview", args=(transcript.pk,))).status_code == 200
    transcript.change_passage_speaker(1250, "Host")
    assert transcript.podlove_data["transcripts"][0]["speaker"] == "Host"
    transcript.correct_passage_text(1250, "Manual words")
    assert transcript.plain_text == "Manual words"
    assert transcript.podlove_data["transcripts"][0]["start"] == "00:00:01.250"


@pytest.mark.parametrize(
    "segment,expected",
    [
        ({"start": "00:00:01.250"}, 1250),
        ({"start": "bad"}, None),
        ({"start_ms": False, "start": "00:00:00.000"}, None),
    ],
)
def test_podlove_timestamp_fallback_keeps_invalid_explicit_identity_invalid(segment, expected):
    from cast.transcripts.podlove import segment_start_ms

    assert segment_start_ms(segment) == expected


def test_named_label_needs_no_dropdown_and_empty_episode_links_to_contributors(admin_client, episode):
    transcript = make_transcript(
        episode.podcast_audio, podlove={"transcripts": [{"speaker": "Host", "start_ms": 0, "text": "Words"}]}
    )
    url = reverse("cast-transcript:edit", args=(transcript.pk,))
    assert "#id_contributor_assignments-FORMS" in admin_client.get(url).content.decode()
    assert (
        'id="id_contributor_assignments-FORMS"'
        in admin_client.get(reverse("wagtailadmin_pages:edit", args=(episode.pk,))).content.decode()
    )
    named_episode(episode)
    response = admin_client.get(url)
    assert response.context["speaker_mapping_rows"][0]["named"]
    assert 'id="id_speaker_0"' not in response.content.decode()
