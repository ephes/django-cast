"""Corrupt synthetic JSON stays available for replacement without editor writes."""

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse

from cast.models import Transcript
from cast.transcripts import services
from tests.known_speaker_apply_test import DOTE, PODLOVE, SPEAKERS, make_transcript


@pytest.fixture(params=["utf8", "depth"])
def corrupt_json(request):
    if request.param == "utf8":
        return b"\xff"
    depth = 100
    return b'{"nested":' * depth + b"0" + b"}" * depth


@pytest.mark.django_db
@pytest.mark.parametrize("field", ["podlove", "dote", "speakers", "corrections"])
@pytest.mark.parametrize("operation", ["get", "speaker", "glossary"])
def test_corrupt_json_is_an_editor_error_without_writes(admin_client, audio, mocker, corrupt_json, field, operation):
    transcript = make_transcript(audio, podlove=PODLOVE, dote=DOTE, speakers=SPEAKERS)
    artifact = getattr(transcript, field)
    artifact.save("corrupt.json", ContentFile(corrupt_json), save=False)
    transcript.save(update_fields=[field])
    before = Transcript.objects.filter(pk=transcript.pk).values().get()
    raw = {name: transcript._read_file_bytes(name) for name in services.EDITOR_ARTIFACT_FIELDS}
    storages = {
        id(getattr(transcript, name).storage): getattr(transcript, name).storage
        for name in services.EDITOR_ARTIFACT_FIELDS
    }
    saves = [mocker.spy(storage, "save") for storage in storages.values()]
    url = reverse("cast-transcript:edit", args=(transcript.pk,))
    if operation == "get":
        response = admin_client.get(url)
    else:
        response = admin_client.post(
            url,
            {
                "action": "review-known-speakers" if operation == "speaker" else "glossary-refresh",
                "artifact_revision": services.artifact_revision(transcript),
                "known_speaker_segment_0": "__blank__",
            },
        )
    assert response.status_code == 400
    assert b"Invalid transcript JSON" in response.content
    assert b"Replace" in response.content
    assert len(str(response.context["artifact_error"])) < 200
    assert Transcript.objects.filter(pk=transcript.pk).values().get() == before
    assert all(spy.call_count == 0 for spy in saves)
    assert {name: transcript._read_file_bytes(name) for name in services.EDITOR_ARTIFACT_FIELDS} == raw
    assert artifact.storage.exists(artifact.name)


@pytest.mark.django_db
@pytest.mark.parametrize("field", ["podlove", "dote", "speakers", "corrections"])
def test_legacy_readers_keep_their_non_editor_fallbacks(audio, corrupt_json, field):
    import json

    transcript = make_transcript(audio)
    getattr(transcript, field).save("corrupt.json", ContentFile(corrupt_json))
    expected = {} if corrupt_json == b"\xff" else json.loads(corrupt_json)
    assert transcript._load_transcript_json(field) == expected
    assert getattr(transcript, f"{field}_data") == expected


@pytest.mark.django_db
@pytest.mark.parametrize("operation", ["speaker", "corrections"])
def test_mutations_preflight_other_corrupt_artifacts(audio, corrupt_json, operation, mocker):
    from cast.transcripts.corrections import refresh_transcript_corrections
    from cast.transcripts.parsing import TranscriptArtifactError

    transcript = make_transcript(audio, podlove=PODLOVE, dote=DOTE, speakers=SPEAKERS)
    field = "dote" if operation == "speaker" else "speakers"
    getattr(transcript, field).save("bad.json", ContentFile(corrupt_json))
    before = Transcript.objects.filter(pk=transcript.pk).values().get()
    stage = mocker.spy(transcript, "_save_file_content")
    with pytest.raises(TranscriptArtifactError):
        if operation == "speaker":
            transcript.save_known_speaker_editor_decisions({0: {"action": "reject", "speaker": ""}})
        else:
            refresh_transcript_corrections(transcript)
    stage.assert_not_called()
    assert Transcript.objects.filter(pk=transcript.pk).values().get() == before


@pytest.mark.django_db
def test_json_decoder_recursion_failure_is_an_editor_error(admin_client, audio, mocker):
    transcript = make_transcript(audio, podlove=PODLOVE)
    decoder = mocker.patch("cast.transcripts.parsing.json")
    decoder.loads.side_effect = RecursionError("synthetic decoder limit")
    response = admin_client.get(reverse("cast-transcript:edit", args=(transcript.pk,)))
    assert response.status_code == 400
    assert b"Invalid transcript JSON" in response.content
    decoder.loads.assert_called_once()


@pytest.mark.django_db
def test_editor_accepts_valid_replacement_of_corrupt_public_json(admin_client, audio, podlove_transcript):
    transcript = make_transcript(audio, podlove=PODLOVE)
    transcript.podlove.save("bad.json", ContentFile(b"\xff"))
    url = reverse("cast-transcript:edit", args=(transcript.pk,))
    page = admin_client.get(url)
    assert page.status_code == 400
    assert b"Save replacement" in page.content
    response = admin_client.post(url, {"audio": audio.pk, "podlove": podlove_transcript})
    assert response.status_code == 302
    assert admin_client.get(url).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("field", ["speakers", "corrections"])
def test_editor_can_detach_corrupt_private_sidecar_without_deleting_bytes(admin_client, audio, field):
    transcript = make_transcript(audio, podlove=PODLOVE)
    artifact = getattr(transcript, field)
    artifact.save("bad.json", ContentFile(b"\xff"))
    old_name = artifact.name
    url = reverse("cast-transcript:edit", args=(transcript.pk,))
    page = admin_client.get(url)
    assert page.status_code == 400
    assert page.context["invalid_sidecars"] == [field]
    response = admin_client.post(
        url,
        {"action": "detach-invalid-sidecar", "field": field, "artifact_revision": page.context["artifact_revision"]},
    )
    assert response.status_code == 302
    transcript.refresh_from_db()
    assert not getattr(transcript, field)
    assert artifact.storage.exists(old_name)
    assert admin_client.get(url).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("field", ["podlove", "", "unknown"])
def test_recovery_rejects_unapproved_fields(admin_client, audio, field):
    transcript = make_transcript(audio, podlove=PODLOVE)
    before = Transcript.objects.filter(pk=transcript.pk).values().get()
    response = admin_client.post(
        reverse("cast-transcript:edit", args=(transcript.pk,)),
        {
            "action": "detach-invalid-sidecar",
            "field": field,
            "artifact_revision": services.artifact_revision(transcript),
        },
    )
    assert response.status_code == 400
    assert Transcript.objects.filter(pk=transcript.pk).values().get() == before


@pytest.mark.django_db
def test_recovery_refuses_valid_or_changed_sidecar(admin_client, audio):
    transcript = make_transcript(audio, podlove=PODLOVE, speakers=SPEAKERS)
    url = reverse("cast-transcript:edit", args=(transcript.pk,))
    data = {
        "action": "detach-invalid-sidecar",
        "field": "speakers",
        "artifact_revision": services.artifact_revision(transcript),
    }
    assert admin_client.post(url, data).status_code == 400
    transcript.speakers.save("new.json", ContentFile(b"{}"))
    assert admin_client.post(url, data).status_code == 409
    transcript.refresh_from_db()
    assert transcript.speakers.name


@pytest.mark.django_db
def test_recovery_does_not_clear_a_racing_replacement(admin_client, audio, monkeypatch):
    from cast.transcripts.parsing import TranscriptArtifactError

    transcript = make_transcript(audio, podlove=PODLOVE)
    transcript.speakers.save("bad.json", ContentFile(b"\xff"))
    original_validate = services.validate_json_artifact

    def replaced_during_check(current, field):
        try:
            original_validate(current, field)
        except TranscriptArtifactError:
            Transcript.objects.filter(pk=current.pk).update(speakers="concurrent-valid.json")
            raise

    monkeypatch.setattr(services, "validate_json_artifact", replaced_during_check)
    response = admin_client.post(
        reverse("cast-transcript:edit", args=(transcript.pk,)),
        {
            "action": "detach-invalid-sidecar",
            "field": "speakers",
            "artifact_revision": services.artifact_revision(transcript),
        },
    )
    assert response.status_code == 409
    transcript.refresh_from_db()
    assert transcript.speakers.name == "concurrent-valid.json"


@pytest.mark.django_db
@pytest.mark.parametrize("field", ["podlove", "speakers"])
def test_corruption_keeps_public_html_and_editor_api_available(
    client, api_client, admin_user, episode, corrupt_json, field
):
    transcript = make_transcript(episode.podcast_audio, podlove=PODLOVE, dote=DOTE, speakers=SPEAKERS)
    getattr(transcript, field).save("corrupt.json", ContentFile(corrupt_json))
    html = client.get(reverse("cast:html-transcript-no-post", kwargs={"transcript_pk": transcript.pk}))
    assert html.status_code == 200
    api_client.force_authenticate(user=admin_user)
    api = api_client.get(reverse("cast:api:editor_episode_transcript", kwargs={"pk": episode.pk}))
    assert api.status_code == 200, api.content
    assert api.json()["transcript"]["id"] == transcript.pk


@pytest.mark.django_db
@pytest.mark.parametrize("unavailable", ["missing", "syntax"])
def test_editor_retains_legacy_missing_and_syntax_fallbacks(admin_client, audio, unavailable):
    transcript = make_transcript(audio, podlove=PODLOVE, speakers=SPEAKERS)
    field = "dote" if unavailable == "missing" else "speakers"
    if unavailable == "missing":
        transcript.dote = "missing.dote.json"
        transcript.save(update_fields=["dote"])
    else:
        transcript.speakers.save("syntax.speakers.json", ContentFile(b"not-json"))
    original_name = getattr(transcript, field).name
    response = admin_client.get(reverse("cast-transcript:edit", args=(transcript.pk,)))
    assert response.status_code == 200
    transcript.refresh_from_db()
    assert getattr(transcript, field).name == original_name
    assert bool(transcript.get_speaker_suggestions()) == (unavailable == "missing")


@pytest.mark.django_db
def test_strict_preflight_uses_fresh_storage_handle(audio, s3_style_fieldfile_reopen_guard):
    from cast.transcripts.parsing import TranscriptArtifactError

    transcript = make_transcript(audio, podlove=PODLOVE)
    transcript.podlove.save("invalid.json", ContentFile(b"\xff"))
    s3_style_fieldfile_reopen_guard()
    with transcript.podlove.open("rb") as file:
        assert file.read() == b"\xff"
    with pytest.raises(TranscriptArtifactError, match="Invalid transcript JSON"):
        services.validate_json_artifact(transcript, "podlove")


@pytest.mark.django_db
def test_invalid_upload_keeps_healthy_editor_speaker_context(admin_client, episode):
    import copy

    from django.core.files.uploadedfile import SimpleUploadedFile

    from cast.models import Contributor, EpisodeContributor

    contributor = Contributor.objects.create(display_name="Synthetic Guest", slug="synthetic-guest")
    assignment = EpisodeContributor.objects.create(
        episode=episode, contributor=contributor, role=EpisodeContributor.ROLE_GUEST
    )
    episode.save_revision()
    podlove = copy.deepcopy(PODLOVE)
    podlove["transcripts"][0].update(speaker="Speaker 1", voice="Speaker 1")
    transcript = make_transcript(episode.podcast_audio, podlove=podlove, speakers=SPEAKERS)
    before = transcript.podlove.name
    response = admin_client.post(
        reverse("cast-transcript:edit", args=(transcript.pk,)),
        {
            "audio": episode.podcast_audio_id,
            "podlove": SimpleUploadedFile("invalid.podlove.json", b"not-json", content_type="application/json"),
        },
    )
    assert response.status_code == 200
    assert "podlove" in response.context["form"].errors
    assert response.context["speaker_labels"] == ["Speaker 1"]
    assert [item.contributor_id for item in response.context["contributor_assignments"]] == [contributor.pk]
    choices = response.context["speaker_mapping_form"].fields["speaker_0"].choices
    assert str(assignment.pk) in {value for value, _label in choices}
    transcript.refresh_from_db()
    assert transcript.podlove.name == before
