import io
import json
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.error import URLError

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
    get_bool_setting,
    get_float_setting,
    get_setting,
    get_transcript_generation,
    get_transcript_generation_status_context,
    normalize_api_base,
    require_setting,
    require_artifact_path,
    resolve_audio_source_url,
    resolve_diarization_speaker_count,
    transcript_complete,
)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


def test_normalize_api_base():
    assert normalize_api_base("https://voxhelm.example") == (
        "https://voxhelm.example",
        "https://voxhelm.example/v1",
    )
    assert normalize_api_base("https://voxhelm.example/v1") == (
        "https://voxhelm.example",
        "https://voxhelm.example/v1",
    )


def test_settings_helpers_and_client_from_settings(settings, monkeypatch):
    settings.CAST_VOXHELM_API_BASE = "https://voxhelm.example"
    settings.CAST_VOXHELM_API_KEY = ""
    settings.CAST_VOXHELM_POLL_INTERVAL = "1.5"
    monkeypatch.setenv("CAST_VOXHELM_API_KEY", "secret")
    monkeypatch.setenv("CAST_VOXHELM_POLL_TIMEOUT", "12.5")
    monkeypatch.setenv("CAST_VOXHELM_REQUEST_TIMEOUT", "45")

    assert get_setting("CAST_VOXHELM_API_BASE") == "https://voxhelm.example"
    assert require_setting("CAST_VOXHELM_API_KEY") == "secret"
    assert get_float_setting("CAST_VOXHELM_POLL_INTERVAL", 2.0) == 1.5
    client = VoxhelmClient.from_settings()
    assert client.api_base == "https://voxhelm.example/v1"
    assert client.api_key == "secret"
    assert client.model == "auto"
    assert client.language == ""
    assert client.diarization_enabled is False
    assert client.job_timeout_seconds == 12.5
    assert client.request_timeout_seconds == 45.0


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        (True, True),
        (False, False),
        (1, True),
        (0, False),
        (" yes ", True),
        ("OFF", False),
    ],
)
def test_get_bool_setting_parses_django_setting_values(settings, configured, expected):
    settings.CAST_BOOL_SETTING = configured

    assert get_bool_setting("CAST_BOOL_SETTING") is expected


def test_get_bool_setting_reads_environment_values(settings, monkeypatch):
    settings.CAST_BOOL_ENV_TRUE = ""
    settings.CAST_BOOL_ENV_FALSE = ""
    monkeypatch.setenv("CAST_BOOL_ENV_TRUE", "on")
    monkeypatch.setenv("CAST_BOOL_ENV_FALSE", "0")

    assert get_bool_setting("CAST_BOOL_ENV_TRUE") is True
    assert get_bool_setting("CAST_BOOL_ENV_FALSE", True) is False


def test_get_bool_setting_treats_blank_strings_as_unset(settings, monkeypatch):
    settings.CAST_BOOL_BLANK_DJANGO = "  "
    settings.CAST_BOOL_BLANK_ENV = ""
    monkeypatch.setenv("CAST_BOOL_BLANK_ENV", "")

    assert get_bool_setting("CAST_BOOL_BLANK_DJANGO", True) is True
    assert get_bool_setting("CAST_BOOL_BLANK_ENV") is False


@pytest.mark.parametrize("configured", ["maybe", 2])
def test_get_bool_setting_rejects_invalid_values(settings, configured):
    settings.CAST_BOOL_INVALID = configured

    with pytest.raises(ImproperlyConfigured, match="CAST_BOOL_INVALID"):
        get_bool_setting("CAST_BOOL_INVALID")


@pytest.mark.django_db
def test_site_settings_override_django_settings(site, settings):
    settings.CAST_VOXHELM_API_BASE = "https://settings.example"
    settings.CAST_VOXHELM_API_KEY = "settings-secret"
    VoxhelmSettings.objects.update_or_create(
        site=site,
        defaults={
            "api_base": "https://site.example",
            "api_token": "site-secret",
            "model": "whisper-1",
            "language": "de",
            "diarization_enabled": True,
        },
    )

    client = VoxhelmClient.from_settings(request_or_site=site)

    assert client.api_base == "https://site.example/v1"
    assert client.api_key == "site-secret"
    assert client.model == "whisper-1"
    assert client.language == "de"
    assert client.diarization_enabled is True


@pytest.mark.django_db
def test_site_settings_can_be_loaded_from_request(site, settings):
    settings.CAST_VOXHELM_API_BASE = "https://settings.example"
    settings.CAST_VOXHELM_API_KEY = "settings-secret"
    VoxhelmSettings.objects.update_or_create(
        site=site,
        defaults={
            "api_base": "https://site.example",
            "api_token": "site-secret",
            "model": "whisper-1",
            "language": "de",
            "diarization_enabled": True,
        },
    )
    request = RequestFactory().get("/", HTTP_HOST=site.hostname)

    client = VoxhelmClient.from_settings(request_or_site=request)

    assert client.api_base == "https://site.example/v1"
    assert client.api_key == "site-secret"
    assert client.diarization_enabled is True


@pytest.mark.django_db
def test_site_settings_explicit_false_overrides_global_diarization_true(site, settings):
    settings.CAST_VOXHELM_API_BASE = "https://settings.example"
    settings.CAST_VOXHELM_API_KEY = "settings-secret"
    settings.CAST_VOXHELM_DIARIZATION_ENABLED = True
    VoxhelmSettings.objects.update_or_create(site=site, defaults={"diarization_enabled": False})

    client = VoxhelmClient.from_settings(request_or_site=site)

    assert client.diarization_enabled is False


@pytest.mark.django_db
def test_site_settings_unset_diarization_inherits_global_true(site, settings):
    settings.CAST_VOXHELM_API_BASE = "https://settings.example"
    settings.CAST_VOXHELM_API_KEY = "settings-secret"
    settings.CAST_VOXHELM_DIARIZATION_ENABLED = True
    VoxhelmSettings.objects.update_or_create(site=site, defaults={"diarization_enabled": None})

    client = VoxhelmClient.from_settings(request_or_site=site)

    assert client.diarization_enabled is True


def test_client_from_settings_reads_diarization_from_django_setting(settings):
    settings.CAST_VOXHELM_API_BASE = "https://voxhelm.example"
    settings.CAST_VOXHELM_API_KEY = "secret"
    settings.CAST_VOXHELM_DIARIZATION_ENABLED = True

    client = VoxhelmClient.from_settings()

    assert client.diarization_enabled is True


def test_client_from_settings_reads_diarization_from_environment(settings, monkeypatch):
    settings.CAST_VOXHELM_API_BASE = "https://voxhelm.example"
    settings.CAST_VOXHELM_API_KEY = "secret"
    settings.CAST_VOXHELM_DIARIZATION_ENABLED = ""
    monkeypatch.setenv("CAST_VOXHELM_DIARIZATION_ENABLED", "true")

    client = VoxhelmClient.from_settings()

    assert client.diarization_enabled is True


def test_client_from_settings_prefers_django_false_over_environment_true(settings, monkeypatch):
    settings.CAST_VOXHELM_API_BASE = "https://voxhelm.example"
    settings.CAST_VOXHELM_API_KEY = "secret"
    settings.CAST_VOXHELM_DIARIZATION_ENABLED = False
    monkeypatch.setenv("CAST_VOXHELM_DIARIZATION_ENABLED", "true")

    client = VoxhelmClient.from_settings()

    assert client.diarization_enabled is False


def test_require_setting_raises_when_missing(settings, monkeypatch):
    settings.CAST_VOXHELM_API_BASE = ""
    monkeypatch.delenv("CAST_VOXHELM_API_BASE", raising=False)

    with pytest.raises(ImproperlyConfigured, match="CAST_VOXHELM_API_BASE"):
        require_setting("CAST_VOXHELM_API_BASE")


def test_resolve_audio_source_url_requires_absolute_url():
    class Field:
        url = "/media/episode.m4a"

    class FakeAudio:
        pk = 1
        uploaded_audio_files = [("m4a", Field())]

    with pytest.raises(VoxhelmError, match="absolute HTTP"):
        resolve_audio_source_url(FakeAudio())


def test_require_artifact_path_errors_when_missing():
    with pytest.raises(VoxhelmError, match="result payload"):
        require_artifact_path({}, "json")
    with pytest.raises(VoxhelmError, match="artifact references"):
        require_artifact_path({"result": {}}, "json")
    with pytest.raises(VoxhelmError, match="'json' artifact"):
        require_artifact_path({"result": {"artifacts": {}}}, "json")


def test_build_failure_message_prefers_error_message():
    assert build_failure_message({"id": "job-1", "state": "failed", "error": {"message": "boom"}}) == "boom"
    assert "canceled" in build_failure_message({"id": "job-2", "state": "canceled"})
    assert "failed" in build_failure_message({"id": "job-3", "state": "failed", "error": {"message": "  "}})


def test_build_audio_task_ref_supports_diarized_variant():
    assert build_audio_task_ref(1) == "cast-audio-1"
    assert build_audio_task_ref(1, diarization_enabled=True) == "cast-audio-1-diarized"
    assert (
        build_audio_task_ref(1, diarization_enabled=True, diarization_speaker_count=4)
        == "cast-audio-1-diarized-4-speakers"
    )


@pytest.mark.django_db
def test_resolve_diarization_speaker_count_counts_unique_episode_contributors(episode):
    first = Contributor.objects.create(display_name="First", slug="first")
    second = Contributor.objects.create(display_name="Second", slug="second")
    hidden = Contributor.objects.create(display_name="Hidden", slug="hidden", visible=False)
    EpisodeContributor.objects.create(episode=episode, contributor=first, role=EpisodeContributor.ROLE_HOST)
    EpisodeContributor.objects.create(episode=episode, contributor=second, role=EpisodeContributor.ROLE_GUEST)
    EpisodeContributor.objects.create(episode=episode, contributor=hidden, role=EpisodeContributor.ROLE_GUEST)

    assert resolve_diarization_speaker_count(episode.podcast_audio) == 3


@pytest.mark.django_db
def test_resolve_diarization_speaker_count_avoids_multi_episode_union(episode, podcast, body):
    first = Contributor.objects.create(display_name="First", slug="first")
    second = Contributor.objects.create(display_name="Second", slug="second")
    third = Contributor.objects.create(display_name="Third", slug="third")
    EpisodeContributor.objects.create(episode=episode, contributor=first, role=EpisodeContributor.ROLE_HOST)
    EpisodeContributor.objects.create(episode=episode, contributor=second, role=EpisodeContributor.ROLE_GUEST)
    other_episode = EpisodeFactory(
        owner=podcast.owner,
        parent=podcast,
        title="other podcast episode",
        slug="other-podcast-entry",
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

    assert resolve_diarization_speaker_count(episode.podcast_audio) is None
    assert resolve_diarization_speaker_count(episode.podcast_audio, episode=episode) == 2


def test_append_diarization_speaker_count_to_task_ref_preserves_unrelated_suffix():
    assert append_diarization_speaker_count_to_task_ref("custom", None) == "custom"
    assert append_diarization_speaker_count_to_task_ref("custom-4-speakers", 4) == "custom-4-speakers"
    assert append_diarization_speaker_count_to_task_ref("custom-2-speakers", 4) == "custom-2-speakers-4-speakers"
    assert (
        append_diarization_speaker_count_to_task_ref("cast-audio-1-diarized-2-speakers", 4)
        == "cast-audio-1-diarized-4-speakers"
    )


def test_count_episode_diarization_speakers_handles_missing_and_sparse_assignments():
    assert count_episode_diarization_speakers(SimpleNamespace()) is None
    assert (
        count_episode_diarization_speakers(
            SimpleNamespace(
                contributor_assignments=[
                    SimpleNamespace(contributor_id=None),
                    SimpleNamespace(contributor_id=1),
                ]
            )
        )
        is None
    )
    assert (
        count_episode_diarization_speakers(
            SimpleNamespace(
                contributor_assignments=[
                    SimpleNamespace(contributor_id=1),
                    SimpleNamespace(contributor_id=2),
                ]
            )
        )
        == 2
    )


def test_resolve_diarization_speaker_count_without_episode_manager():
    assert resolve_diarization_speaker_count(SimpleNamespace()) is None


def test_client_submit_job_and_download_artifact(mocker):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        if request.full_url.endswith("/v1/jobs"):
            return FakeResponse(b'{"id": "job-1", "state": "queued"}')
        return FakeResponse(b"artifact-bytes")

    mocker.patch("cast.voxhelm.urlopen", side_effect=fake_urlopen)
    client = VoxhelmClient(
        api_base="https://voxhelm.example",
        api_key="secret",
        job_timeout_seconds=5.0,
        request_timeout_seconds=0.75,
    )

    payload = client.submit_transcription_job(
        source_url="https://media.example.com/episode.mp3",
        task_ref="cast-audio-1",
        context={"audio_id": 1},
    )
    artifact = client.download_artifact("/v1/jobs/job-1/artifacts/transcript.vtt")

    assert payload == {"id": "job-1", "state": "queued"}
    assert artifact == b"artifact-bytes"
    request_obj = requests[0][0]
    assert requests[0][1] == 0.75
    assert requests[1][1] == 0.75
    assert request_obj.full_url == "https://voxhelm.example/v1/jobs"
    assert request_obj.headers["Authorization"] == "Bearer secret"
    assert json.loads(request_obj.data.decode("utf-8")) == {
        "job_type": "transcribe",
        "priority": "normal",
        "lane": "batch",
        "backend": "auto",
        "model": "auto",
        "input": {"kind": "url", "url": "https://media.example.com/episode.mp3"},
        "output": {"formats": ["podlove", "dote", "vtt"]},
        "context": {"audio_id": 1},
        "task_ref": "cast-audio-1",
    }


def test_client_submit_job_includes_diarization_when_enabled(mocker):
    client = VoxhelmClient(api_base="https://voxhelm.example", api_key="secret", diarization_enabled=True)
    request_json = mocker.patch.object(client, "request_json", return_value={"id": "job-1"})

    client.submit_transcription_job(
        source_url="https://media.example.com/episode.mp3",
        task_ref="cast-audio-1",
        context={"audio_id": 1},
    )

    assert request_json.call_args.kwargs["payload"]["diarization"] == {"enabled": True}


def test_client_submit_job_includes_diarization_speaker_count_when_provided(mocker):
    client = VoxhelmClient(api_base="https://voxhelm.example", api_key="secret", diarization_enabled=True)
    request_json = mocker.patch.object(client, "request_json", return_value={"id": "job-1"})

    client.submit_transcription_job(
        source_url="https://media.example.com/episode.mp3",
        task_ref="cast-audio-1-diarized-4-speakers",
        context={"audio_id": 1},
        speaker_count=4,
    )

    assert request_json.call_args.kwargs["payload"]["diarization"] == {"enabled": True, "num_speakers": 4}


def test_client_submit_job_rejects_invalid_speaker_count():
    client = VoxhelmClient(api_base="https://voxhelm.example", api_key="secret", diarization_enabled=True)

    with pytest.raises(VoxhelmError, match="speaker_count"):
        client.submit_transcription_job(
            source_url="https://media.example.com/episode.mp3",
            task_ref="cast-audio-1",
            context={"audio_id": 1},
            speaker_count=0,
        )


def test_client_build_url_variants_and_get_job(mocker):
    client = VoxhelmClient(api_base="https://voxhelm.example/v1", api_key="secret")
    request_json = mocker.patch.object(client, "request_json", return_value={"id": "job-1"})

    assert client.build_url("https://other.example/path") == "https://other.example/path"
    assert client.build_url("/v1/jobs/job-1") == "https://voxhelm.example/v1/jobs/job-1"
    assert client.get_job("job-1") == {"id": "job-1"}
    request_json.assert_called_once_with(method="GET", path="jobs/job-1")


def test_client_request_bytes_skips_auth_for_third_party_artifacts(mocker):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse(b"artifact-bytes")

    mocker.patch("cast.voxhelm.urlopen", side_effect=fake_urlopen)
    client = VoxhelmClient(api_base="https://voxhelm.example", api_key="secret")

    artifact = client.download_artifact("https://cdn.example.com/transcripts/job-1.vtt")

    assert artifact == b"artifact-bytes"
    assert requests[0][0].headers.get("Authorization") is None


def test_client_request_json_requires_object_response(mocker):
    mocker.patch("cast.voxhelm.urlopen", return_value=FakeResponse(b'["not-an-object"]'))
    client = VoxhelmClient(api_base="https://voxhelm.example", api_key="secret")

    with pytest.raises(VoxhelmError, match="non-object"):
        client.request_json(method="GET", path="jobs/job-1")


def test_client_http_error_includes_body(mocker):
    error = HTTPError(
        url="https://voxhelm.example/v1/jobs",
        code=502,
        msg="Bad Gateway",
        hdrs=None,
        fp=io.BytesIO(b"upstream broke"),
    )
    mocker.patch("cast.voxhelm.urlopen", side_effect=error)
    client = VoxhelmClient(api_base="https://voxhelm.example", api_key="secret")

    with pytest.raises(VoxhelmError, match="502: upstream broke"):
        client.request_bytes(method="GET", path="jobs/job-1")


def test_client_url_error_is_wrapped(mocker):
    mocker.patch("cast.voxhelm.urlopen", side_effect=URLError("offline"))
    client = VoxhelmClient(api_base="https://voxhelm.example", api_key="secret")

    with pytest.raises(VoxhelmError, match="offline"):
        client.request_bytes(method="GET", path="jobs/job-1")


def test_client_submit_job_includes_language_when_configured(settings, mocker):
    settings.CAST_VOXHELM_API_BASE = "https://voxhelm.example"
    settings.CAST_VOXHELM_API_KEY = "secret"
    settings.CAST_VOXHELM_LANGUAGE = "de"
    client = VoxhelmClient.from_settings()
    request_json = mocker.patch.object(client, "request_json", return_value={"id": "job-1"})

    client.submit_transcription_job(
        source_url="https://media.example.com/episode.mp3",
        task_ref="cast-audio-1",
        context={"audio_id": 1},
    )

    assert request_json.call_args.kwargs["payload"]["language"] == "de"


def test_client_submit_job_uses_explicit_model_and_empty_language(mocker):
    client = VoxhelmClient(api_base="https://voxhelm.example", api_key="secret", model="whisper-1", language="")
    request_json = mocker.patch.object(client, "request_json", return_value={"id": "job-1"})

    client.submit_transcription_job(
        source_url="https://media.example.com/episode.mp3",
        task_ref="cast-audio-2",
        context={"audio_id": 2},
    )

    payload = request_json.call_args.kwargs["payload"]
    assert payload["model"] == "whisper-1"
    assert "language" not in payload


def test_client_rejects_non_bool_diarization_enabled():
    with pytest.raises(TypeError, match="diarization_enabled must be a bool"):
        VoxhelmClient(api_base="https://voxhelm.example", api_key="secret", diarization_enabled="false")  # type: ignore[arg-type]


def test_client_wait_for_job_times_out(mocker):
    client = VoxhelmClient(
        api_base="https://voxhelm.example",
        api_key="secret",
        poll_interval_seconds=0.0,
        job_timeout_seconds=5.0,
    )
    mocker.patch.object(client, "get_job", return_value={"id": "job-1", "state": "queued"})
    mocker.patch("cast.voxhelm.monotonic", side_effect=[0.0, 5.1])
    mocker.patch("cast.voxhelm.sleep")

    with pytest.raises(VoxhelmError, match="Timed out"):
        client.wait_for_job("job-1")


def test_client_wait_for_job_polls_until_terminal_state(mocker):
    client = VoxhelmClient(
        api_base="https://voxhelm.example",
        api_key="secret",
        poll_interval_seconds=0.0,
        job_timeout_seconds=5.0,
    )
    get_job = mocker.patch.object(
        client,
        "get_job",
        side_effect=[{"id": "job-1", "state": "queued"}, {"id": "job-1", "state": "succeeded"}],
    )
    sleep_mock = mocker.patch("cast.voxhelm.sleep")

    assert client.wait_for_job("job-1") == {"id": "job-1", "state": "succeeded"}
    assert get_job.call_count == 2
    sleep_mock.assert_called_once_with(0.0)


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

        def submit_transcription_job(self, *, source_url, task_ref, context, speaker_count=None):
            self.submit_calls.append((source_url, task_ref, context, speaker_count))
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
        def submit_transcription_job(self, *, source_url, task_ref, context, speaker_count=None):
            assert source_url == audio.m4a.url
            assert task_ref == build_audio_task_ref(audio.pk)
            assert context == {"consumer": "django-cast", "audio_id": audio.pk}
            assert speaker_count is None
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

        def submit_transcription_job(self, *, source_url, task_ref, context, speaker_count=None):
            del source_url, context
            assert task_ref == build_audio_task_ref(audio.pk, diarization_enabled=True)
            assert speaker_count is None
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
        def submit_transcription_job(self, *, source_url, task_ref, context, speaker_count=None):
            del source_url, task_ref, context, speaker_count
            return {"id": "job-failed", "state": "failed", "error": {"message": "boom"}}

    with pytest.raises(VoxhelmError, match="boom"):
        VoxhelmTranscriptService(client=StubClient()).submit_for_audio(audio)


@pytest.mark.django_db
def test_submit_for_audio_requires_job_id(settings, user, m4a_audio):
    settings.MEDIA_URL = "https://media.example.com/"
    audio = Audio(user=user, m4a=m4a_audio, title="episode")
    audio.save(duration=False, cache_file_sizes=False)

    class StubClient:
        def submit_transcription_job(self, *, source_url, task_ref, context, speaker_count=None):
            del source_url, task_ref, context, speaker_count
            return {"state": "queued"}

    with pytest.raises(VoxhelmError, match="job id"):
        VoxhelmTranscriptService(client=StubClient()).submit_for_audio(audio)


def test_transcript_service_collection_helpers(mocker):
    get_or_create = mocker.patch("cast.voxhelm.Transcript.objects.get_or_create", return_value=("transcript", True))
    audio = SimpleNamespace(collection_id=None)

    assert VoxhelmTranscriptService._get_or_create_transcript(audio=audio) == (
        "transcript",
        True,
    )
    assert get_or_create.call_args.kwargs == {"audio": audio, "defaults": {}}

    transcript = SimpleNamespace(collection_id=None)
    VoxhelmTranscriptService._update_collection(
        transcript=transcript,
        audio=SimpleNamespace(collection_id=1, collection="root"),
    )
    assert transcript.collection == "root"


@pytest.mark.django_db
def test_enqueue_audio_transcript_generation_creates_local_state(mocker, audio, site):
    submission = TranscriptSubmission(
        job_id="job-queued",
        source_url="https://media.example.com/audio.m4a",
        task_ref=build_audio_task_ref(audio.pk),
        job_payload={"id": "job-queued", "state": "queued"},
    )
    service = mocker.Mock()
    service.submit_for_audio.return_value = submission
    service_cls = mocker.patch("cast.voxhelm.VoxhelmTranscriptService", return_value=service)
    enqueue_mock = mocker.Mock(return_value=SimpleNamespace(id="task-123"))
    mocker.patch("cast.voxhelm_tasks.complete_transcript_generation", new=SimpleNamespace(enqueue=enqueue_mock))

    result = enqueue_audio_transcript_generation(audio=audio, request_or_site=site, requested_by=audio.user)

    assert result.enqueued is True
    generation = get_transcript_generation(audio)
    assert generation is not None
    assert generation.status == TranscriptGeneration.Status.QUEUED
    assert generation.task_ref == build_audio_task_ref(audio.pk)
    assert generation.voxhelm_job_id == "job-queued"
    assert generation.task_result_id == "task-123"
    assert generation.source_url == "https://media.example.com/audio.m4a"
    assert generation.site == site
    assert generation.requested_by == audio.user
    service_cls.assert_called_once_with(request_or_site=site)
    service.submit_for_audio.assert_called_once_with(
        audio,
        task_ref=build_audio_task_ref(audio.pk),
        episode=None,
    )
    enqueue_mock.assert_called_once_with(generation.pk)


@pytest.mark.django_db
def test_enqueue_audio_transcript_generation_reuses_active_job(mocker, audio):
    generation = TranscriptGeneration.objects.create(
        audio=audio,
        status=TranscriptGeneration.Status.RUNNING,
        task_ref=build_audio_task_ref(audio.pk),
        voxhelm_job_id="job-running",
        task_result_id="task-1",
        source_url="https://media.example.com/audio.m4a",
    )
    submit = mocker.patch("cast.voxhelm.VoxhelmTranscriptService.submit_for_audio")

    result = enqueue_audio_transcript_generation(audio=audio)

    assert result.enqueued is False
    assert result.generation.pk == generation.pk
    submit.assert_not_called()


@pytest.mark.django_db
def test_enqueue_audio_transcript_generation_reuses_active_job_found_after_initial_lookup(mocker, audio):
    generation = TranscriptGeneration.objects.create(
        audio=audio,
        status=TranscriptGeneration.Status.RUNNING,
        task_ref=build_audio_task_ref(audio.pk),
        voxhelm_job_id="job-running",
        task_result_id="task-1",
        source_url="https://media.example.com/audio.m4a",
    )
    service = mocker.Mock()
    service.client = SimpleNamespace(diarization_enabled=False)
    mocker.patch("cast.voxhelm.VoxhelmTranscriptService", return_value=service)
    mocker.patch("cast.voxhelm.get_transcript_generation", return_value=None)

    result = enqueue_audio_transcript_generation(audio=audio)

    assert result.enqueued is False
    assert result.generation.pk == generation.pk
    service.submit_for_audio.assert_not_called()


@pytest.mark.django_db
def test_enqueue_audio_transcript_generation_uses_diarized_task_ref_from_site_settings(mocker, audio, site, settings):
    settings.CAST_VOXHELM_API_BASE = "https://settings.example"
    settings.CAST_VOXHELM_API_KEY = "settings-secret"
    VoxhelmSettings.objects.update_or_create(
        site=site,
        defaults={
            "api_base": "https://site.example",
            "api_token": "site-secret",
            "diarization_enabled": True,
        },
    )
    task_ref = build_audio_task_ref(audio.pk, diarization_enabled=True)
    submission = TranscriptSubmission(
        job_id="job-diarized",
        source_url="https://media.example.com/audio.m4a",
        task_ref=task_ref,
        job_payload={"id": "job-diarized", "state": "queued"},
    )
    submit = mocker.patch("cast.voxhelm.VoxhelmTranscriptService.submit_for_audio", return_value=submission)
    enqueue_mock = mocker.Mock(return_value=SimpleNamespace(id="task-123"))
    mocker.patch("cast.voxhelm_tasks.complete_transcript_generation", new=SimpleNamespace(enqueue=enqueue_mock))

    result = enqueue_audio_transcript_generation(audio=audio, request_or_site=site, requested_by=audio.user)

    assert result.enqueued is True
    generation = get_transcript_generation(audio)
    assert generation is not None
    assert generation.task_ref == task_ref
    assert generation.voxhelm_job_id == "job-diarized"
    submit.assert_called_once_with(audio, task_ref=task_ref, episode=None)


@pytest.mark.django_db
def test_enqueue_audio_transcript_generation_uses_episode_speaker_count(mocker, episode):
    audio = episode.podcast_audio
    assert audio is not None
    for index in range(4):
        contributor = Contributor.objects.create(display_name=f"Speaker {index}", slug=f"enqueue-speaker-{index}")
        EpisodeContributor.objects.create(
            episode=episode,
            contributor=contributor,
            role=EpisodeContributor.ROLE_GUEST,
        )
    task_ref = build_audio_task_ref(audio.pk, diarization_enabled=True, diarization_speaker_count=4)
    submission = TranscriptSubmission(
        job_id="job-diarized",
        source_url="https://media.example.com/audio.m4a",
        task_ref=task_ref,
        job_payload={"id": "job-diarized", "state": "queued"},
    )
    service = mocker.Mock()
    service.client = SimpleNamespace(diarization_enabled=True)
    service.submit_for_audio.return_value = submission
    mocker.patch("cast.voxhelm.VoxhelmTranscriptService", return_value=service)
    enqueue_mock = mocker.Mock(return_value=SimpleNamespace(id="task-123"))
    mocker.patch("cast.voxhelm_tasks.complete_transcript_generation", new=SimpleNamespace(enqueue=enqueue_mock))

    result = enqueue_audio_transcript_generation(audio=audio, episode=episode)

    generation = get_transcript_generation(audio)
    assert result.enqueued is True
    assert generation is not None
    assert generation.task_ref == task_ref
    service.submit_for_audio.assert_called_once_with(audio, task_ref=task_ref, episode=episode)


@pytest.mark.django_db
def test_enqueue_audio_transcript_generation_requeues_inactive_generation_with_diarized_task_ref(mocker, audio):
    generation = TranscriptGeneration.objects.create(
        audio=audio,
        status=TranscriptGeneration.Status.SUCCEEDED,
        task_ref=build_audio_task_ref(audio.pk),
        voxhelm_job_id="job-old",
        task_result_id="task-old",
        source_url="https://media.example.com/audio.m4a",
    )
    task_ref = build_audio_task_ref(audio.pk, diarization_enabled=True)
    submission = TranscriptSubmission(
        job_id="job-diarized",
        source_url="https://media.example.com/audio.m4a",
        task_ref=task_ref,
        job_payload={"id": "job-diarized", "state": "queued"},
    )
    service = mocker.Mock()
    service.client = SimpleNamespace(diarization_enabled=True)
    service.submit_for_audio.return_value = submission
    mocker.patch("cast.voxhelm.VoxhelmTranscriptService", return_value=service)
    enqueue_mock = mocker.Mock(return_value=SimpleNamespace(id="task-123"))
    mocker.patch("cast.voxhelm_tasks.complete_transcript_generation", new=SimpleNamespace(enqueue=enqueue_mock))

    result = enqueue_audio_transcript_generation(audio=audio)

    generation.refresh_from_db()
    assert result.enqueued is True
    assert result.generation.pk == generation.pk
    assert generation.task_ref == task_ref
    assert generation.voxhelm_job_id == "job-diarized"
    service.submit_for_audio.assert_called_once_with(audio, task_ref=task_ref, episode=None)


@pytest.mark.django_db
def test_enqueue_audio_transcript_generation_requires_saved_audio():
    unsaved_audio = SimpleNamespace(pk=None)

    with pytest.raises(VoxhelmError, match="must be saved"):
        enqueue_audio_transcript_generation(audio=unsaved_audio)  # type: ignore[arg-type]


@pytest.mark.django_db
def test_enqueue_audio_transcript_generation_marks_failed_when_enqueue_fails(mocker, audio, site):
    submission = TranscriptSubmission(
        job_id="job-queued",
        source_url="https://media.example.com/audio.m4a",
        task_ref=build_audio_task_ref(audio.pk),
        job_payload={"id": "job-queued", "state": "queued"},
    )
    service = mocker.Mock()
    service.submit_for_audio.return_value = submission
    mocker.patch("cast.voxhelm.VoxhelmTranscriptService", return_value=service)
    enqueue_mock = mocker.Mock(side_effect=RuntimeError("queue broke"))
    mocker.patch("cast.voxhelm_tasks.complete_transcript_generation", new=SimpleNamespace(enqueue=enqueue_mock))

    with pytest.raises(RuntimeError, match="queue broke"):
        enqueue_audio_transcript_generation(audio=audio, request_or_site=site, requested_by=audio.user)

    generation = get_transcript_generation(audio)
    assert generation is not None
    assert generation.status == TranscriptGeneration.Status.FAILED
    assert generation.error_message == "queue broke"


@pytest.mark.django_db
def test_enqueue_audio_transcript_generation_marks_failed_when_initial_submit_fails(mocker, audio, site):
    service = mocker.Mock()
    service.submit_for_audio.side_effect = VoxhelmError("voxhelm offline")
    mocker.patch("cast.voxhelm.VoxhelmTranscriptService", return_value=service)

    with pytest.raises(VoxhelmError, match="voxhelm offline"):
        enqueue_audio_transcript_generation(audio=audio, request_or_site=site, requested_by=audio.user)

    generation = get_transcript_generation(audio)
    assert generation is not None
    assert generation.status == TranscriptGeneration.Status.FAILED
    assert generation.error_message == "voxhelm offline"
    assert generation.voxhelm_job_id == ""


@pytest.mark.django_db
def test_enqueue_audio_transcript_generation_preserves_existing_failed_row_when_retry_submit_fails(
    mocker, audio, site
):
    generation = TranscriptGeneration.objects.create(
        audio=audio,
        status=TranscriptGeneration.Status.FAILED,
        task_ref=build_audio_task_ref(audio.pk),
        error_message="older failure",
    )
    service = mocker.Mock()
    service.submit_for_audio.side_effect = VoxhelmError("voxhelm still offline")
    mocker.patch("cast.voxhelm.VoxhelmTranscriptService", return_value=service)

    with pytest.raises(VoxhelmError, match="voxhelm still offline"):
        enqueue_audio_transcript_generation(audio=audio, request_or_site=site, requested_by=audio.user)

    generation.refresh_from_db()
    assert generation.status == TranscriptGeneration.Status.FAILED
    assert generation.error_message == "older failure"


@pytest.mark.django_db
def test_complete_transcript_generation_marks_success_and_calls_service(mocker, audio):
    generation = TranscriptGeneration.objects.create(
        audio=audio,
        status=TranscriptGeneration.Status.QUEUED,
        task_ref=build_audio_task_ref(audio.pk),
        voxhelm_job_id="job-42",
        task_result_id="task-42",
        source_url="https://media.example.com/audio.m4a",
    )
    service = mocker.Mock()
    mocker.patch("cast.voxhelm_tasks.VoxhelmTranscriptService", return_value=service)

    complete_transcript_generation.call(generation.pk)

    generation.refresh_from_db()
    assert generation.status == TranscriptGeneration.Status.SUCCEEDED
    service.complete_audio_job.assert_called_once_with(
        audio,
        job_id="job-42",
        source_url="https://media.example.com/audio.m4a",
    )


@pytest.mark.django_db
def test_complete_transcript_generation_returns_when_already_succeeded(mocker, audio):
    generation = TranscriptGeneration.objects.create(
        audio=audio,
        status=TranscriptGeneration.Status.SUCCEEDED,
        task_ref=build_audio_task_ref(audio.pk),
    )
    service_cls = mocker.patch("cast.voxhelm_tasks.VoxhelmTranscriptService")

    complete_transcript_generation.call(generation.pk)

    service_cls.assert_not_called()


@pytest.mark.django_db
def test_complete_transcript_generation_marks_failure_on_exception(mocker, audio):
    generation = TranscriptGeneration.objects.create(
        audio=audio,
        status=TranscriptGeneration.Status.QUEUED,
        task_ref=build_audio_task_ref(audio.pk),
        voxhelm_job_id="job-43",
        source_url="https://media.example.com/audio.m4a",
    )
    service = mocker.Mock()
    service.complete_audio_job.side_effect = VoxhelmError("worker broke")
    mocker.patch("cast.voxhelm_tasks.VoxhelmTranscriptService", return_value=service)

    with pytest.raises(VoxhelmError, match="worker broke"):
        complete_transcript_generation.call(generation.pk)

    generation.refresh_from_db()
    assert generation.status == TranscriptGeneration.Status.FAILED
    assert generation.error_message == "worker broke"


@pytest.mark.django_db
def test_get_transcript_generation_status_context_exposes_failed_state(audio):
    TranscriptGeneration.objects.create(
        audio=audio,
        status=TranscriptGeneration.Status.FAILED,
        task_ref=build_audio_task_ref(audio.pk),
        error_message="upstream broke",
    )

    context = get_transcript_generation_status_context(audio=audio)

    assert context["transcript_generation_active"] is False
    assert context["transcript_generation_status"] == "Failed"
    assert context["transcript_generation_error"] == "upstream broke"


@pytest.mark.django_db
def test_get_transcript_generation_status_context_links_succeeded_transcript(audio):
    transcript = create_transcript(audio=audio)
    TranscriptGeneration.objects.create(
        audio=audio,
        status=TranscriptGeneration.Status.SUCCEEDED,
        task_ref=build_audio_task_ref(audio.pk),
    )

    context = get_transcript_generation_status_context(audio=audio)

    assert context["transcript_generation_status"] == "Succeeded"
    assert context["transcript_generation_transcript_url"] == reverse("cast-transcript:edit", args=(transcript.pk,))


@pytest.mark.django_db
def test_generate_for_audio_updates_existing_transcript(settings, user, m4a_audio):
    settings.MEDIA_URL = "https://media.example.com/"
    audio = Audio(user=user, m4a=m4a_audio, title="episode", collection=Collection.get_first_root_node())
    audio.save(duration=False, cache_file_sizes=False)

    from cast.devdata import create_transcript

    existing = create_transcript(
        audio=audio,
        podlove={"transcripts": [{"text": "old"}]},
        vtt="WEBVTT\n\n00:00:00.000 --> 00:00:00.100\nold\n",
        dote={
            "lines": [
                {
                    "startTime": "00:00:00,000",
                    "endTime": "00:00:00,100",
                    "speakerDesignation": "",
                    "text": "old",
                }
            ]
        },
    )
    old_paths = existing.get_all_paths()

    class StubClient:
        def submit_transcription_job(self, *, source_url, task_ref, context, speaker_count=None):
            assert source_url == audio.m4a.url
            assert task_ref == f"cast-audio-{audio.pk}"
            assert context == {"consumer": "django-cast", "audio_id": audio.pk}
            assert speaker_count is None
            return {
                "id": "job-2",
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
                                "start": "00:00:02.000",
                                "start_ms": 2000,
                                "end": "00:00:04.000",
                                "end_ms": 4000,
                                "speaker": "",
                                "voice": "",
                                "text": "fresh transcript",
                            }
                        ],
                    }
                ).encode("utf-8")
            if artifact_path == "/dote":
                return json.dumps(
                    {
                        "lines": [
                            {
                                "startTime": "00:00:02,000",
                                "endTime": "00:00:04,000",
                                "speakerDesignation": "",
                                "text": "fresh transcript",
                            }
                        ]
                    }
                ).encode("utf-8")
            if artifact_path == "/vtt":
                return b"WEBVTT\n\n00:00:02.000 --> 00:00:04.000\nfresh transcript\n"
            raise AssertionError(f"unexpected artifact: {artifact_path}")

    result = VoxhelmTranscriptService(client=StubClient()).generate_for_audio(audio)

    existing.refresh_from_db()
    assert result.created is False
    assert existing.get_all_paths() != old_paths
    assert existing.collection_id == audio.collection_id
    assert existing.podlove_data["transcripts"][0]["text"] == "fresh transcript"
    assert existing.dote_data["lines"][0]["text"] == "fresh transcript"
    with existing.vtt.open("r") as handle:
        assert handle.read() == "WEBVTT\n\n00:00:02.000 --> 00:00:04.000\nfresh transcript\n"


@pytest.mark.django_db
def test_generate_for_audio_waits_for_queued_job(settings, user, m4a_audio):
    settings.MEDIA_URL = "https://media.example.com/"
    audio = Audio(user=user, m4a=m4a_audio, title="episode")
    audio.save(duration=False, cache_file_sizes=False)

    class StubClient:
        def submit_transcription_job(self, *, source_url, task_ref, context, speaker_count=None):
            del source_url, task_ref, context, speaker_count
            return {"id": "job-3", "state": "queued"}

        def wait_for_job(self, job_id):
            assert job_id == "job-3"
            return {"id": "job-3", "state": "failed", "error": {"message": "transcription failed"}}

        def download_artifact(self, artifact_path):
            raise AssertionError(f"unexpected artifact: {artifact_path}")

    with pytest.raises(VoxhelmError, match="transcription failed"):
        VoxhelmTranscriptService(client=StubClient()).generate_for_audio(audio)


@pytest.mark.django_db
def test_complete_audio_job_ignores_mismatched_initial_payload(settings, user, m4a_audio):
    settings.MEDIA_URL = "https://media.example.com/"
    audio = Audio(user=user, m4a=m4a_audio, title="episode")
    audio.save(duration=False, cache_file_sizes=False)

    class StubClient:
        def wait_for_job(self, job_id):
            assert job_id == "job-5"
            return {
                "id": "job-5",
                "state": "succeeded",
                "result": {"artifacts": {"podlove": "/podlove", "dote": "/dote", "vtt": "/vtt"}},
            }

        def download_artifact(self, artifact_path):
            if artifact_path == "/podlove":
                return b'{"version": 1, "transcripts": [{"text": "done"}]}'
            if artifact_path == "/dote":
                return b'{"lines": [{"text": "done"}]}'
            if artifact_path == "/vtt":
                return b"WEBVTT\n"
            raise AssertionError(f"unexpected artifact: {artifact_path}")

    result = VoxhelmTranscriptService(client=StubClient()).complete_audio_job(
        audio,
        job_id="job-5",
        source_url=audio.m4a.url,
        initial_job_payload={"id": "job-other", "state": "succeeded"},
    )

    assert result.job_id == "job-5"


@pytest.mark.django_db
@pytest.mark.parametrize("missing_format", ["podlove", "dote", "vtt"])
def test_generate_for_audio_requires_required_artifacts(settings, user, m4a_audio, missing_format):
    settings.MEDIA_URL = "https://media.example.com/"
    audio = Audio(user=user, m4a=m4a_audio, title="episode")
    audio.save(duration=False, cache_file_sizes=False)

    class StubClient:
        def submit_transcription_job(self, *, source_url, task_ref, context, speaker_count=None):
            del source_url, task_ref, context, speaker_count
            artifacts = {"podlove": "/podlove", "dote": "/dote", "vtt": "/vtt"}
            artifacts.pop(missing_format)
            return {"id": "job-4", "state": "succeeded", "result": {"artifacts": artifacts}}

        def wait_for_job(self, job_id):
            raise AssertionError(f"wait_for_job should not run for terminal jobs: {job_id}")

        def download_artifact(self, artifact_path):
            if artifact_path == "/podlove":
                return b'{"version": 1, "transcripts": []}'
            if artifact_path == "/dote":
                return b'{"lines": []}'
            if artifact_path == "/vtt":
                return b"WEBVTT\n"
            raise AssertionError(f"unexpected artifact: {artifact_path}")

    with pytest.raises(VoxhelmError, match=rf"'{missing_format}' artifact"):
        VoxhelmTranscriptService(client=StubClient()).generate_for_audio(audio)
