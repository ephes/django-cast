# ruff: noqa: F401,F811,I001
import io
import json
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.request import Request

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory
from django.urls import reverse
from wagtail.models import Collection

from cast.devdata import create_transcript
from cast.models import Audio, Contributor, EpisodeContributor, TranscriptGeneration, VoxhelmSettings
from cast.voxhelm_tasks import complete_transcript_generation
from tests.factories import EpisodeFactory
from cast.voxhelm import (
    NoRedirectHandler,
    TranscriptGenerationResult,
    TranscriptSubmission,
    VoxhelmClient,
    VoxhelmError,
    VoxhelmTranscriptService,
    append_diarization_speaker_count_to_task_ref,
    build_audio_task_ref,
    build_failure_message,
    count_episode_diarization_speakers,
    enqueue_audio_transcript_generation,
    ensure_diarized_task_ref,
    get_bool_setting,
    get_float_setting,
    get_setting,
    get_transcript_generation,
    get_transcript_generation_status_context,
    normalize_api_base,
    open_url,
    read_response_bytes,
    require_setting,
    require_artifact_path,
    replace_file,
    resolve_audio_source_url,
    resolve_audio_diarization_enabled,
    resolve_audio_task_ref,
    resolve_diarization_speaker_count,
    strip_diarized_task_ref,
    transcript_complete,
    validate_transcript_artifacts,
)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


VALID_PODLOVE_ARTIFACT = b'{"transcripts": [{"text": "done"}]}'
VALID_DOTE_ARTIFACT = (
    b'{"lines": [{"startTime": "00:00:00,000", "endTime": "00:00:00,100", "speakerDesignation": "", "text": "done"}]}'
)
VALID_VTT_ARTIFACT = b"WEBVTT\n\n00:00:00.000 --> 00:00:00.100\ndone\n"


def test_transcript_complete_requires_non_empty_artifacts():
    complete = SimpleNamespace(
        podlove="podlove.json",
        vtt="transcript.vtt",
        dote="dote.json",
        podlove_data={"transcripts": [{"text": "Hello"}]},
        dote_data={"lines": [{"text": "Hello"}]},
    )
    empty_podlove = SimpleNamespace(
        podlove="podlove.json",
        vtt="transcript.vtt",
        dote="dote.json",
        podlove_data={"transcripts": []},
        dote_data={"lines": [{"text": "Hello"}]},
    )
    empty_dote = SimpleNamespace(
        podlove="podlove.json",
        vtt="transcript.vtt",
        dote="dote.json",
        podlove_data={"transcripts": [{"text": "Hello"}]},
        dote_data={"lines": []},
    )

    assert transcript_complete(complete) is True
    assert transcript_complete(empty_podlove) is False
    assert transcript_complete(empty_dote) is False


def test_replace_file_stages_fresh_file_without_deleting_old():
    class Storage:
        def __init__(self):
            self.events = []

        def save(self, name, _content):
            self.events.append(("save", name))
            return name

        def delete(self, name):
            self.events.append(("delete", name))

    storage = Storage()
    field = SimpleNamespace(name="old-transcript.json", storage=storage)

    replace_file(field, "new-transcript.json", b"new transcript")

    assert field.name.startswith("new-transcript-")
    assert field.name.endswith(".json")
    assert storage.events == [("save", field.name)]


@pytest.mark.django_db
def test_generate_for_audio_creates_transcript(settings, user, m4a_audio):
    settings.MEDIA_URL = "https://media.example.com/"
    settings.CAST_VOXHELM_API_BASE = "https://voxhelm.example"
    settings.CAST_VOXHELM_API_KEY = "secret"
    audio = Audio(user=user, m4a=m4a_audio, title="episode", collection=Collection.get_first_root_node())
    audio.save(duration=False, cache_file_sizes=False)

    class StubClient:
        def __init__(self):
            self.submit_calls = []

        def submit_transcription_job(
            self, *, source_url, task_ref, context, speaker_count=None, diarization_enabled=None
        ):
            self.submit_calls.append((source_url, task_ref, context, speaker_count))
            assert diarization_enabled is False
            return {
                "id": "job-1",
                "state": "succeeded",
                "result": {"artifacts": {"podlove": "/podlove", "dote": "/dote", "vtt": "/vtt"}},
            }

        def wait_for_job(self, job_id):
            raise AssertionError(f"wait_for_job should not run for terminal jobs: {job_id}")

        def download_artifact(self, artifact_path):
            if artifact_path == "/podlove":
                return json.dumps(
                    {
                        "version": 1,
                        "transcripts": [
                            {
                                "start": "00:00:00.000",
                                "start_ms": 0,
                                "end": "00:00:01.500",
                                "end_ms": 1500,
                                "speaker": "Speaker 1",
                                "voice": "Speaker 1",
                                "text": "Hello world",
                            },
                            {
                                "start": "00:00:01.500",
                                "start_ms": 1500,
                                "end": "00:00:03.000",
                                "end_ms": 3000,
                                "speaker": "Speaker 2",
                                "voice": "Speaker 2",
                                "text": "Hi there",
                            },
                        ],
                    }
                ).encode("utf-8")
            if artifact_path == "/dote":
                return json.dumps(
                    {
                        "lines": [
                            {
                                "startTime": "00:00:00,000",
                                "endTime": "00:00:01,500",
                                "speakerDesignation": "Speaker 1",
                                "text": "Hello world",
                            },
                            {
                                "startTime": "00:00:01,500",
                                "endTime": "00:00:03,000",
                                "speakerDesignation": "Speaker 2",
                                "text": "Hi there",
                            },
                        ]
                    }
                ).encode("utf-8")
            if artifact_path == "/vtt":
                return b"WEBVTT\n\n00:00:00.000 --> 00:00:01.500\nHello world\n"
            raise AssertionError(f"unexpected artifact: {artifact_path}")

    client = StubClient()
    result = VoxhelmTranscriptService(client=client).generate_for_audio(audio)

    assert isinstance(result, TranscriptGenerationResult)
    assert result.created is True
    assert result.job_id == "job-1"
    assert result.source_url == audio.m4a.url
    result.transcript.refresh_from_db()
    assert transcript_complete(result.transcript) is True
    assert result.transcript.podlove_data == {
        "version": 1,
        "transcripts": [
            {
                "start": "00:00:00.000",
                "start_ms": 0,
                "end": "00:00:01.500",
                "end_ms": 1500,
                "speaker": "Speaker 1",
                "voice": "Speaker 1",
                "text": "Hello world",
            },
            {
                "start": "00:00:01.500",
                "start_ms": 1500,
                "end": "00:00:03.000",
                "end_ms": 3000,
                "speaker": "Speaker 2",
                "voice": "Speaker 2",
                "text": "Hi there",
            },
        ],
    }
    assert result.transcript.dote_data == {
        "lines": [
            {
                "startTime": "00:00:00,000",
                "endTime": "00:00:01,500",
                "speakerDesignation": "Speaker 1",
                "text": "Hello world",
            },
            {
                "startTime": "00:00:01,500",
                "endTime": "00:00:03,000",
                "speakerDesignation": "Speaker 2",
                "text": "Hi there",
            },
        ]
    }
    with result.transcript.vtt.open("r") as handle:
        assert handle.read() == "WEBVTT\n\n00:00:00.000 --> 00:00:01.500\nHello world\n"
    assert client.submit_calls == [
        (
            audio.m4a.url,
            f"cast-audio-{audio.pk}",
            {"consumer": "django-cast", "audio_id": audio.pk},
            None,
        )
    ]


def test_generate_for_audio_requires_saved_audio():
    class FakeAudio:
        pk = None

    with pytest.raises(VoxhelmError, match="must be saved"):
        VoxhelmTranscriptService(client=object()).generate_for_audio(FakeAudio())  # type: ignore[arg-type]


@pytest.mark.django_db
def test_submit_for_audio_returns_submission_metadata(settings, user, m4a_audio):
    settings.MEDIA_URL = "https://media.example.com/"
    audio = Audio(user=user, m4a=m4a_audio, title="episode")
    audio.save(duration=False, cache_file_sizes=False)

    class StubClient:
        def submit_transcription_job(
            self, *, source_url, task_ref, context, speaker_count=None, diarization_enabled=None
        ):
            assert source_url == audio.m4a.url
            assert task_ref == build_audio_task_ref(audio.pk)
            assert context == {"consumer": "django-cast", "audio_id": audio.pk}
            assert speaker_count is None
            assert diarization_enabled is False
            return {"id": "job-submit", "state": "queued"}

    submission = VoxhelmTranscriptService(client=StubClient()).submit_for_audio(audio)

    assert submission == TranscriptSubmission(
        job_id="job-submit",
        source_url=audio.m4a.url,
        task_ref=build_audio_task_ref(audio.pk),
        job_payload={"id": "job-submit", "state": "queued"},
    )


@pytest.mark.django_db
def test_submit_for_audio_uses_diarized_task_ref_for_diarized_client(settings, user, m4a_audio):
    settings.MEDIA_URL = "https://media.example.com/"
    audio = Audio(user=user, m4a=m4a_audio, title="episode")
    audio.save(duration=False, cache_file_sizes=False)

    class StubClient:
        diarization_enabled = True

        def submit_transcription_job(
            self, *, source_url, task_ref, context, speaker_count=None, diarization_enabled=None
        ):
            del source_url, context
            assert task_ref == build_audio_task_ref(audio.pk, diarization_enabled=True)
            assert speaker_count is None
            assert diarization_enabled is True
            return {"id": "job-submit", "state": "queued"}

    submission = VoxhelmTranscriptService(client=StubClient()).submit_for_audio(audio)

    assert submission.task_ref == build_audio_task_ref(audio.pk, diarization_enabled=True)


@pytest.mark.django_db
def test_submit_for_audio_with_real_diarized_client_uses_diarized_task_ref_and_payload(
    settings, user, m4a_audio, mocker
):
    settings.MEDIA_URL = "https://media.example.com/"
    audio = Audio(user=user, m4a=m4a_audio, title="episode")
    audio.save(duration=False, cache_file_sizes=False)
    client = VoxhelmClient(api_base="https://voxhelm.example", api_key="secret", diarization_enabled=True)
    request_json = mocker.patch.object(client, "request_json", return_value={"id": "job-submit", "state": "queued"})

    submission = VoxhelmTranscriptService(client=client).submit_for_audio(audio)

    payload = request_json.call_args.kwargs["payload"]
    assert submission.task_ref == build_audio_task_ref(audio.pk, diarization_enabled=True)
    assert payload["task_ref"] == build_audio_task_ref(audio.pk, diarization_enabled=True)
    assert payload["diarization"] == {"enabled": True}


@pytest.mark.django_db
def test_submit_for_audio_enabled_mode_overrides_disabled_client(settings, user, m4a_audio, mocker):
    settings.MEDIA_URL = "https://media.example.com/"
    audio = Audio(
        user=user,
        m4a=m4a_audio,
        title="episode",
        transcript_diarization_mode=Audio.TranscriptDiarizationMode.ENABLED,
    )
    audio.save(duration=False, cache_file_sizes=False)
    client = VoxhelmClient(api_base="https://voxhelm.example", api_key="secret", diarization_enabled=False)
    request_json = mocker.patch.object(client, "request_json", return_value={"id": "job-submit", "state": "queued"})

    submission = VoxhelmTranscriptService(client=client).submit_for_audio(audio)

    payload = request_json.call_args.kwargs["payload"]
    assert submission.task_ref == build_audio_task_ref(audio.pk, diarization_enabled=True)
    assert payload["task_ref"] == build_audio_task_ref(audio.pk, diarization_enabled=True)
    assert payload["diarization"] == {"enabled": True}


@pytest.mark.django_db
def test_submit_for_audio_disabled_mode_overrides_diarized_client_and_skips_speaker_hint(settings, episode, mocker):
    settings.MEDIA_URL = "https://media.example.com/"
    first = Contributor.objects.create(display_name="Disabled First", slug="disabled-first")
    second = Contributor.objects.create(display_name="Disabled Second", slug="disabled-second")
    EpisodeContributor.objects.create(episode=episode, contributor=first, role=EpisodeContributor.ROLE_HOST)
    EpisodeContributor.objects.create(episode=episode, contributor=second, role=EpisodeContributor.ROLE_GUEST)
    audio = episode.podcast_audio
    audio.transcript_diarization_mode = Audio.TranscriptDiarizationMode.DISABLED
    audio.save(update_fields=["transcript_diarization_mode"], duration=False, cache_file_sizes=False)
    client = VoxhelmClient(api_base="https://voxhelm.example", api_key="secret", diarization_enabled=True)
    request_json = mocker.patch.object(client, "request_json", return_value={"id": "job-submit", "state": "queued"})

    submission = VoxhelmTranscriptService(client=client).submit_for_audio(
        audio,
        task_ref=build_audio_task_ref(audio.pk, diarization_enabled=True, diarization_speaker_count=2),
        episode=episode,
    )

    payload = request_json.call_args.kwargs["payload"]
    assert submission.task_ref == build_audio_task_ref(audio.pk)
    assert payload["task_ref"] == build_audio_task_ref(audio.pk)
    assert "diarization" not in payload


@pytest.mark.django_db
def test_submit_for_audio_uses_episode_contributor_count_as_diarization_hint(settings, episode, mocker):
    settings.MEDIA_URL = "https://media.example.com/"
    first = Contributor.objects.create(display_name="First", slug="first")
    second = Contributor.objects.create(display_name="Second", slug="second")
    third = Contributor.objects.create(display_name="Third", slug="third")
    fourth = Contributor.objects.create(display_name="Fourth", slug="fourth")
    for contributor in (first, second, third, fourth):
        EpisodeContributor.objects.create(
            episode=episode,
            contributor=contributor,
            role=EpisodeContributor.ROLE_GUEST,
        )
    audio = episode.podcast_audio
    client = VoxhelmClient(api_base="https://voxhelm.example", api_key="secret", diarization_enabled=True)
    request_json = mocker.patch.object(client, "request_json", return_value={"id": "job-submit", "state": "queued"})

    submission = VoxhelmTranscriptService(client=client).submit_for_audio(audio)

    expected_task_ref = build_audio_task_ref(audio.pk, diarization_enabled=True, diarization_speaker_count=4)
    payload = request_json.call_args.kwargs["payload"]
    assert submission.task_ref == expected_task_ref
    assert payload["task_ref"] == expected_task_ref
    assert payload["diarization"] == {"enabled": True, "num_speakers": 4}


@pytest.mark.django_db
def test_submit_for_audio_skips_speaker_hint_for_multi_episode_audio(settings, episode, podcast, body, mocker):
    settings.MEDIA_URL = "https://media.example.com/"
    first = Contributor.objects.create(display_name="First", slug="multi-first")
    second = Contributor.objects.create(display_name="Second", slug="multi-second")
    third = Contributor.objects.create(display_name="Third", slug="multi-third")
    EpisodeContributor.objects.create(episode=episode, contributor=first, role=EpisodeContributor.ROLE_HOST)
    EpisodeContributor.objects.create(episode=episode, contributor=second, role=EpisodeContributor.ROLE_GUEST)
    other_episode = EpisodeFactory(
        owner=podcast.owner,
        parent=podcast,
        title="another podcast episode",
        slug="another-podcast-entry",
        podcast_audio=episode.podcast_audio,
        body=body,
    )
    EpisodeContributor.objects.create(
        episode=other_episode,
        contributor=first,
        role=EpisodeContributor.ROLE_HOST,
    )
    EpisodeContributor.objects.create(
        episode=other_episode,
        contributor=third,
        role=EpisodeContributor.ROLE_GUEST,
    )
    audio = episode.podcast_audio
    client = VoxhelmClient(api_base="https://voxhelm.example", api_key="secret", diarization_enabled=True)
    request_json = mocker.patch.object(client, "request_json", return_value={"id": "job-submit", "state": "queued"})

    submission = VoxhelmTranscriptService(client=client).submit_for_audio(audio)

    payload = request_json.call_args.kwargs["payload"]
    assert submission.task_ref == build_audio_task_ref(audio.pk, diarization_enabled=True)
    assert payload["task_ref"] == build_audio_task_ref(audio.pk, diarization_enabled=True)
    assert payload["diarization"] == {"enabled": True}


@pytest.mark.django_db
def test_submit_for_audio_appends_speaker_count_to_supplied_task_ref(settings, episode, mocker):
    settings.MEDIA_URL = "https://media.example.com/"
    for index in range(4):
        contributor = Contributor.objects.create(display_name=f"Speaker {index}", slug=f"speaker-{index}")
        EpisodeContributor.objects.create(
            episode=episode,
            contributor=contributor,
            role=EpisodeContributor.ROLE_GUEST,
        )
    audio = episode.podcast_audio
    client = VoxhelmClient(api_base="https://voxhelm.example", api_key="secret", diarization_enabled=True)
    request_json = mocker.patch.object(client, "request_json", return_value={"id": "job-submit", "state": "queued"})

    submission = VoxhelmTranscriptService(client=client).submit_for_audio(
        audio,
        task_ref=build_audio_task_ref(audio.pk, diarization_enabled=True),
        episode=episode,
    )

    expected_task_ref = build_audio_task_ref(audio.pk, diarization_enabled=True, diarization_speaker_count=4)
    payload = request_json.call_args.kwargs["payload"]
    assert submission.task_ref == expected_task_ref
    assert payload["task_ref"] == expected_task_ref
    assert payload["diarization"] == {"enabled": True, "num_speakers": 4}


@pytest.mark.django_db
def test_submit_for_audio_raises_for_terminal_failed_state(settings, user, m4a_audio):
    settings.MEDIA_URL = "https://media.example.com/"
    audio = Audio(user=user, m4a=m4a_audio, title="episode")
    audio.save(duration=False, cache_file_sizes=False)

    class StubClient:
        def submit_transcription_job(
            self, *, source_url, task_ref, context, speaker_count=None, diarization_enabled=None
        ):
            del source_url, task_ref, context, speaker_count, diarization_enabled
            return {"id": "job-failed", "state": "failed", "error": {"message": "boom"}}

    with pytest.raises(VoxhelmError, match="boom"):
        VoxhelmTranscriptService(client=StubClient()).submit_for_audio(audio)


@pytest.mark.django_db
def test_submit_for_audio_requires_job_id(settings, user, m4a_audio):
    settings.MEDIA_URL = "https://media.example.com/"
    audio = Audio(user=user, m4a=m4a_audio, title="episode")
    audio.save(duration=False, cache_file_sizes=False)

    class StubClient:
        def submit_transcription_job(
            self, *, source_url, task_ref, context, speaker_count=None, diarization_enabled=None
        ):
            del source_url, task_ref, context, speaker_count, diarization_enabled
            return {"state": "queued"}

    with pytest.raises(VoxhelmError, match="job id"):
        VoxhelmTranscriptService(client=StubClient()).submit_for_audio(audio)
