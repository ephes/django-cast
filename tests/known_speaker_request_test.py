"""Tests for the django-cast known-speaker request + reviewable suggestion storage.

These cover the sender side (building the Voxhelm known-speaker reference
payload from approved contributor voice references and the opt-in setting) and
the storage side (persisting the private ``speakers`` suggestion sidecar).
"""

import json
from types import SimpleNamespace

import pytest
from django.core.files.base import ContentFile

from cast.models import Contributor, Transcript
from cast.models.contributors import ContributorVoiceReference
from cast.voxhelm import (
    VoxhelmClient,
    VoxhelmError,
    VoxhelmTranscriptService,
    build_known_speaker_reference_entry,
    build_known_speaker_references,
    client_known_speaker_enabled,
    optional_artifact_path,
)


def make_clip(name="voice.wav"):
    return ContentFile(b"RIFF....WAVEfmt ", name=name)


def approved_clip_reference(contributor, **kwargs):
    kwargs.setdefault("clip", make_clip())
    return ContributorVoiceReference.objects.create(
        contributor=contributor,
        status=ContributorVoiceReference.Status.APPROVED,
        consent_confirmed=True,
        **kwargs,
    )


def episode_with(*contributors):
    return SimpleNamespace(
        contributor_assignments=[SimpleNamespace(contributor_id=c.pk, contributor=c) for c in contributors]
    )


# --------------------------------------------------------------------------- #
# Settings opt-in + client payload
# --------------------------------------------------------------------------- #


def test_client_from_settings_reads_known_speaker_enabled(settings):
    settings.CAST_VOXHELM_API_BASE = "https://voxhelm.example"
    settings.CAST_VOXHELM_API_KEY = "secret"
    settings.CAST_VOXHELM_KNOWN_SPEAKER_ENABLED = True

    client = VoxhelmClient.from_settings()

    assert client.known_speaker_enabled is True


def test_client_rejects_non_bool_known_speaker_enabled():
    with pytest.raises(TypeError):
        VoxhelmClient(api_base="https://voxhelm.example", api_key="x", known_speaker_enabled="yes")


def test_client_known_speaker_enabled_helper_is_strict():
    assert client_known_speaker_enabled(SimpleNamespace()) is False
    assert client_known_speaker_enabled(SimpleNamespace(known_speaker_enabled=True)) is True


def test_client_submit_job_includes_known_speakers(mocker):
    client = VoxhelmClient(api_base="https://voxhelm.example", api_key="secret", diarization_enabled=True)
    request_json = mocker.patch.object(client, "request_json", return_value={"id": "job-1"})
    known_speakers = [
        {
            "id": "1",
            "name": "Johannes",
            "references": [{"kind": "clip_artifact", "audio": {"kind": "url", "url": "https://cdn.example/a.wav"}}],
        }
    ]

    client.submit_transcription_job(
        source_url="https://media.example.com/episode.mp3",
        task_ref="cast-audio-1-diarized",
        context={"audio_id": 1},
        speaker_count=4,
        known_speakers=known_speakers,
    )

    diarization = request_json.call_args.kwargs["payload"]["diarization"]
    assert diarization["strategy"] == "pyannote_known_speaker"
    assert diarization["known_speakers"] == known_speakers
    assert diarization["num_speakers"] == 4


def test_client_submit_job_omits_known_speakers_when_diarization_disabled(mocker):
    client = VoxhelmClient(api_base="https://voxhelm.example", api_key="secret", diarization_enabled=False)
    request_json = mocker.patch.object(client, "request_json", return_value={"id": "job-1"})

    client.submit_transcription_job(
        source_url="https://media.example.com/episode.mp3",
        task_ref="cast-audio-1",
        context={"audio_id": 1},
        known_speakers=[{"id": "1", "name": "X", "references": []}],
        diarization_enabled=False,
    )

    assert "diarization" not in request_json.call_args.kwargs["payload"]


# --------------------------------------------------------------------------- #
# build_known_speaker_reference_entry
# --------------------------------------------------------------------------- #


def test_reference_entry_for_source_range(mocker):
    mocker.patch("cast.voxhelm.resolve_audio_source_url", return_value="https://cdn.example/pp.m4a")
    reference = SimpleNamespace(
        is_source_range=True,
        source_audio_id=7,
        source_audio=SimpleNamespace(),
        start_seconds=10,
        end_seconds=25,
        clip=None,
    )
    assert build_known_speaker_reference_entry(reference) == {
        "kind": "source_range",
        "audio": {"kind": "url", "url": "https://cdn.example/pp.m4a"},
        "start": 10.0,
        "end": 25.0,
    }


def test_reference_entry_source_range_skipped_when_url_unresolvable(mocker):
    mocker.patch("cast.voxhelm.resolve_audio_source_url", side_effect=VoxhelmError("no url"))
    reference = SimpleNamespace(
        is_source_range=True,
        source_audio_id=7,
        source_audio=SimpleNamespace(),
        start_seconds=1,
        end_seconds=2,
        clip=None,
    )
    assert build_known_speaker_reference_entry(reference) is None


def test_reference_entry_for_absolute_clip():
    reference = SimpleNamespace(
        is_source_range=False,
        source_audio_id=None,
        clip=SimpleNamespace(url="https://cdn.example/clip.wav"),
    )
    assert build_known_speaker_reference_entry(reference) == {
        "kind": "clip_artifact",
        "audio": {"kind": "url", "url": "https://cdn.example/clip.wav"},
    }


def test_reference_entry_skips_non_absolute_clip():
    reference = SimpleNamespace(
        is_source_range=False,
        source_audio_id=None,
        clip=SimpleNamespace(url="/media/clip.wav"),
    )
    assert build_known_speaker_reference_entry(reference) is None


def test_reference_entry_skips_private_clip_without_url():
    class PrivateClip:
        @property
        def url(self):
            raise ValueError("This private file is not accessible via a URL.")

    reference = SimpleNamespace(
        is_source_range=False,
        source_audio_id=None,
        clip=PrivateClip(),
    )
    assert build_known_speaker_reference_entry(reference) is None


def test_reference_entry_returns_none_without_clip_or_range():
    reference = SimpleNamespace(is_source_range=False, source_audio_id=None, clip=None)
    assert build_known_speaker_reference_entry(reference) is None


# --------------------------------------------------------------------------- #
# build_known_speaker_references
# --------------------------------------------------------------------------- #


def test_build_references_returns_empty_for_missing_episode_or_assignments():
    assert build_known_speaker_references(None) == []
    assert build_known_speaker_references(SimpleNamespace()) == []
    assert build_known_speaker_references(SimpleNamespace(contributor_assignments=[])) == []


def test_build_references_resolves_queryset_like_assignments():
    # An assignments manager exposes .all(); the builder must call it.
    episode = SimpleNamespace(contributor_assignments=SimpleNamespace(all=lambda: []))
    assert build_known_speaker_references(episode) == []


def approved_range_reference(contributor, audio, start, end, **kwargs):
    return ContributorVoiceReference.objects.create(
        contributor=contributor,
        source_audio=audio,
        start_seconds=start,
        end_seconds=end,
        status=ContributorVoiceReference.Status.APPROVED,
        consent_confirmed=True,
        **kwargs,
    )


@pytest.mark.django_db
def test_build_references_groups_approved_references_by_contributor(mocker, audio):
    mocker.patch("cast.voxhelm.resolve_audio_source_url", return_value="https://cdn.example/pp.m4a")
    johannes = Contributor.objects.create(display_name="Johannes", slug="johannes")
    dominik = Contributor.objects.create(display_name="Dominik", slug="dominik")
    approved_range_reference(johannes, audio, "10.0", "20.0")
    approved_range_reference(johannes, audio, "30.0", "40.0")
    approved_range_reference(dominik, audio, "5.0", "9.0")
    # Pending reference must be excluded.
    ContributorVoiceReference.objects.create(contributor=dominik, clip=make_clip("pending.wav"))

    known = build_known_speaker_references(episode_with(johannes, dominik))

    assert [k["name"] for k in known] == ["Johannes", "Dominik"]
    assert known[0]["id"] == str(johannes.pk)
    assert len(known[0]["references"]) == 2
    assert len(known[1]["references"]) == 1
    assert all(r["kind"] == "source_range" for r in known[0]["references"])


@pytest.mark.django_db
def test_build_references_excludes_hidden_contributor_without_optin(mocker, audio):
    mocker.patch("cast.voxhelm.resolve_audio_source_url", return_value="https://cdn.example/pp.m4a")
    hidden = Contributor.objects.create(display_name="Hidden", slug="hidden", visible=False)
    approved_range_reference(hidden, audio, "1.0", "2.0")
    assert build_known_speaker_references(episode_with(hidden)) == []


@pytest.mark.django_db
def test_build_references_includes_hidden_contributor_when_opted_in(mocker, audio):
    mocker.patch("cast.voxhelm.resolve_audio_source_url", return_value="https://cdn.example/pp.m4a")
    hidden = Contributor.objects.create(display_name="Hidden", slug="hidden", visible=False)
    approved_range_reference(hidden, audio, "1.0", "2.0", allow_for_hidden_contributor=True)
    known = build_known_speaker_references(episode_with(hidden))
    assert [k["name"] for k in known] == ["Hidden"]


@pytest.mark.django_db
def test_build_references_skips_contributor_without_resolvable_references(mocker, audio):
    # A contributor with only a source-range reference whose URL cannot resolve.
    speaker = Contributor.objects.create(display_name="NoUrl", slug="nourl")
    ContributorVoiceReference.objects.create(
        contributor=speaker,
        source_audio=audio,
        start_seconds="1.0",
        end_seconds="2.0",
        status=ContributorVoiceReference.Status.APPROVED,
        consent_confirmed=True,
    )
    mocker.patch("cast.voxhelm.resolve_audio_source_url", side_effect=VoxhelmError("no url"))
    assert build_known_speaker_references(episode_with(speaker)) == []


@pytest.mark.django_db
def test_build_references_skips_private_clip_reference_without_crashing(tmp_path, settings):
    settings.CAST_PRIVATE_MEDIA_ROOT = str(tmp_path / "private")
    speaker = Contributor.objects.create(display_name="Private Clip", slug="private-clip-reference")
    approved_clip_reference(speaker)

    assert build_known_speaker_references(episode_with(speaker)) == []


@pytest.mark.django_db
def test_build_references_ignores_assignments_without_contributor():
    episode = SimpleNamespace(
        contributor_assignments=[
            SimpleNamespace(contributor_id=None, contributor=None),
        ]
    )
    assert build_known_speaker_references(episode) == []


# --------------------------------------------------------------------------- #
# optional_artifact_path
# --------------------------------------------------------------------------- #


def test_optional_artifact_path_variants():
    assert optional_artifact_path({}, "speakers") is None
    assert optional_artifact_path({"result": "x"}, "speakers") is None
    assert optional_artifact_path({"result": {"artifacts": "x"}}, "speakers") is None
    assert optional_artifact_path({"result": {"artifacts": {}}}, "speakers") is None
    payload = {"result": {"artifacts": {"speakers": "/v1/jobs/1/artifacts/transcript.speakers.json"}}}
    assert optional_artifact_path(payload, "speakers") == "/v1/jobs/1/artifacts/transcript.speakers.json"


# --------------------------------------------------------------------------- #
# submit_for_audio sends references; complete_audio_job stores the sidecar
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
def test_submit_for_audio_sends_known_speakers(settings, user, m4a_audio, mocker, audio):
    settings.MEDIA_URL = "https://media.example.com/"
    mocker.patch("cast.voxhelm.resolve_audio_source_url", return_value="https://cdn.example/ref.m4a")
    johannes = Contributor.objects.create(display_name="Johannes", slug="johannes")
    approved_range_reference(johannes, audio, "10.0", "20.0")
    client = VoxhelmClient(
        api_base="https://voxhelm.example",
        api_key="secret",
        diarization_enabled=True,
        known_speaker_enabled=True,
    )
    request_json = mocker.patch.object(client, "request_json", return_value={"id": "job", "state": "queued"})

    VoxhelmTranscriptService(client=client).submit_for_audio(audio, episode=episode_with(johannes))

    diarization = request_json.call_args.kwargs["payload"]["diarization"]
    assert diarization["strategy"] == "pyannote_known_speaker"
    assert diarization["known_speakers"][0]["name"] == "Johannes"
    assert diarization["known_speakers"][0]["references"][0]["kind"] == "source_range"


@pytest.mark.django_db
def test_submit_for_audio_omits_known_speakers_when_disabled(settings, mocker, audio):
    settings.MEDIA_URL = "https://media.example.com/"
    mocker.patch("cast.voxhelm.resolve_audio_source_url", return_value="https://cdn.example/ref.m4a")
    johannes = Contributor.objects.create(display_name="Johannes", slug="johannes")
    approved_range_reference(johannes, audio, "10.0", "20.0")
    # diarization on, but known_speaker_enabled off -> no strategy/known_speakers.
    client = VoxhelmClient(api_base="https://voxhelm.example", api_key="secret", diarization_enabled=True)
    request_json = mocker.patch.object(client, "request_json", return_value={"id": "job", "state": "queued"})

    VoxhelmTranscriptService(client=client).submit_for_audio(audio, episode=episode_with(johannes))

    assert "strategy" not in request_json.call_args.kwargs["payload"]["diarization"]


class FakeCompleteClient:
    def __init__(self, artifacts):
        self._artifacts = artifacts
        self._bytes = {
            "/podlove": b'{"transcripts": []}',
            "/dote": b'{"lines": []}',
            "/vtt": b"WEBVTT\n",
            "/speakers": json.dumps(
                {
                    "version": 1,
                    "summary": {"strategy": "pyannote_known_speaker", "uncertain_segment_count": 1},
                    "segments": [
                        {"index": 0, "speaker": "Johannes", "speaker_uncertain": False},
                        {"index": 1, "speaker": None, "speaker_uncertain": True},
                        "not-a-dict",
                    ],
                }
            ).encode("utf-8"),
        }

    def wait_for_job(self, job_id):
        return {"id": job_id, "state": "succeeded", "result": {"artifacts": self._artifacts}}

    def download_artifact(self, path):
        return self._bytes[path]


@pytest.mark.django_db
def test_complete_audio_job_stores_speaker_suggestions(audio):
    client = FakeCompleteClient({"podlove": "/podlove", "dote": "/dote", "vtt": "/vtt", "speakers": "/speakers"})
    result = VoxhelmTranscriptService(client=client).complete_audio_job(
        audio, job_id="job", source_url="https://media.example.com/episode.mp3"
    )
    transcript = result.transcript
    assert transcript.speakers
    suggestions = transcript.get_speaker_suggestions()
    assert [s["speaker"] for s in suggestions] == ["Johannes", None]  # non-dict entry filtered out
    assert transcript.has_uncertain_speaker_suggestions() is True
    assert transcript.get_speaker_suggestion_summary()["strategy"] == "pyannote_known_speaker"
    # The private sidecar is not part of the public transcript file set.
    assert transcript.speakers.name not in transcript.get_all_paths()


@pytest.mark.django_db
def test_complete_audio_job_without_speakers_artifact_leaves_field_empty(audio):
    client = FakeCompleteClient({"podlove": "/podlove", "dote": "/dote", "vtt": "/vtt"})
    result = VoxhelmTranscriptService(client=client).complete_audio_job(
        audio, job_id="job", source_url="https://media.example.com/episode.mp3"
    )
    assert not result.transcript.speakers
    assert result.transcript.get_speaker_suggestions() == []


# --------------------------------------------------------------------------- #
# Transcript suggestion helpers
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
def test_transcript_speakers_helpers_with_no_file(audio):
    transcript = Transcript.objects.create(audio=audio)
    assert transcript.speakers_data == {}
    assert transcript.get_speaker_suggestions() == []
    assert transcript.get_speaker_suggestion_summary() == {}
    assert transcript.has_uncertain_speaker_suggestions() is False


@pytest.mark.django_db
def test_transcript_speakers_data_handles_invalid_json(audio):
    transcript = Transcript.objects.create(audio=audio)
    transcript.speakers.save("bad.json", ContentFile(b"not json"), save=True)
    assert transcript.speakers_data == {}


@pytest.mark.django_db
def test_transcript_speakers_data_handles_non_object_json(audio):
    transcript = Transcript.objects.create(audio=audio)
    transcript.speakers.save("list.json", ContentFile(b"[1, 2, 3]"), save=True)
    assert transcript.speakers_data == {}
    assert transcript.get_speaker_suggestion_summary() == {}
