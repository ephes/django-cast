"""Synthetic artifact admission regressions through editor and apply seams."""

import copy
from io import BytesIO

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse

from cast.transcripts import known_speakers, parsing, services
from tests.transcripts.known_speaker_apply_helpers import DOTE, PODLOVE, SPEAKERS, make_transcript


@pytest.mark.parametrize("value", [[], {}, True, False, 1])
def test_editor_action_requires_a_string(value):
    assert known_speakers.normalize_editor_decision({"action": value}) is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field",
    [
        "speaker",
        "raw_diarization_speaker",
        "speaker_uncertain",
        "speaker_accept_reason",
        "speaker_uncertain_reason",
        "editor_decision",
        "editor_decision.action",
        "editor_decision.speaker",
    ],
)
@pytest.mark.parametrize("value", [[], {}, True])
def test_malformed_sidecar_refuses_review_and_apply(admin_client, audio, mocker, field, value):
    data = copy.deepcopy(SPEAKERS)
    if "." in field:
        decision = {"action": "correct", "speaker": "Synthetic"}
        decision[field.split(".")[1]] = value
        data["segments"][0]["editor_decision"] = decision
    else:
        data["segments"][0][field] = value
    # True is valid only for the actual boolean discriminator.
    if field == "speaker_uncertain" and value is True:
        data["segments"][0][field] = "true"
    transcript = make_transcript(audio, podlove=PODLOVE, dote=DOTE, speakers=data)
    raw = {name: transcript._read_file_bytes(name) for name in services.EDITOR_ARTIFACT_FIELDS}
    save = mocker.spy(transcript, "_save_file_content")
    url = reverse("cast-transcript:edit", args=(transcript.pk,))
    assert admin_client.get(url).status_code == 400
    assert (
        admin_client.post(
            url,
            {
                "action": "review-known-speakers",
                "artifact_revision": services.artifact_revision(transcript),
                "known_speaker_segment_0": "__blank__",
            },
        ).status_code
        == 400
    )
    assert transcript.get_speaker_suggestions() == []
    with pytest.raises(parsing.TranscriptArtifactError):
        transcript.apply_known_speaker_suggestions()
    save.assert_not_called()
    assert {name: transcript._read_file_bytes(name) for name in services.EDITOR_ARTIFACT_FIELDS} == raw


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field,raw",
    [
        ("podlove", b'{"transcripts":[{"text":"a","text":"b"}]}'),
        ("dote", b'{"lines":[{"speakerDesignation":"a","speakerDesignation":"a"}]}'),
        ("speakers", b'{"segments":[{"editor_decision":null,"editor_decision":{}}]}'),
    ],
)
def test_duplicate_members_refuse_read_edit_and_apply(admin_client, audio, mocker, field, raw):
    transcript = make_transcript(audio, podlove=PODLOVE, dote=DOTE, speakers=SPEAKERS)
    getattr(transcript, field).save("duplicate.json", ContentFile(raw))
    before = {name: transcript._read_file_bytes(name) for name in services.EDITOR_ARTIFACT_FIELDS}
    with pytest.raises(parsing.TranscriptArtifactError):
        parsing.read_json_artifact(BytesIO(raw))
    assert admin_client.get(reverse("cast-transcript:edit", args=(transcript.pk,))).status_code == 400
    save = mocker.spy(transcript, "_save_file_content")
    with pytest.raises(parsing.TranscriptArtifactError):
        transcript.apply_known_speaker_suggestions()
    with pytest.raises(parsing.TranscriptArtifactError):
        transcript.save_known_speaker_editor_decisions({0: {"action": "reject"}})
    save.assert_not_called()
    assert {name: transcript._read_file_bytes(name) for name in services.EDITOR_ARTIFACT_FIELDS} == before


def test_sibling_object_members_are_distinct():
    assert parsing.read_json_artifact(BytesIO(b'[{"text":"a"},{"text":"b"}]')) == [{"text": "a"}, {"text": "b"}]


@pytest.mark.parametrize("value", [[], {}, True])
@pytest.mark.parametrize("action", ["approve", "reject"])
def test_editor_decision_speaker_requires_text(value, action):
    assert known_speakers.normalize_editor_decision({"action": action, "speaker": value}) is None


def test_sidecar_shape_validation():
    known_speakers.validate_sidecar(None)
    for segments in (None, {}, True):
        with pytest.raises(parsing.TranscriptArtifactError):
            known_speakers.validate_sidecar({"segments": segments})


@pytest.mark.django_db
def test_malformed_private_sidecar_keeps_readonly_api_available(api_client, admin_user, episode):
    transcript = make_transcript(episode.podcast_audio, podlove=PODLOVE, speakers={"segments": [{"speaker": []}]})
    api_client.force_authenticate(user=admin_user)
    response = api_client.get(reverse("cast:api:editor_episode_transcript", kwargs={"pk": episode.pk}))
    assert response.status_code == 200
    assert response.json()["transcript"]["id"] == transcript.pk
