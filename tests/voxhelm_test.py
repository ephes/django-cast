import io
import json
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.error import URLError

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory
from wagtail.models import Collection

from cast.models import Audio, VoxhelmSettings
from cast.voxhelm import (
    TranscriptGenerationResult,
    VoxhelmClient,
    VoxhelmError,
    VoxhelmTranscriptService,
    build_failure_message,
    get_float_setting,
    get_setting,
    normalize_api_base,
    normalized_segments,
    render_dote,
    render_podlove,
    require_setting,
    require_artifact_path,
    resolve_audio_source_url,
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
    assert client.job_timeout_seconds == 12.5
    assert client.request_timeout_seconds == 45.0


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
        },
    )

    client = VoxhelmClient.from_settings(request_or_site=site)

    assert client.api_base == "https://site.example/v1"
    assert client.api_key == "site-secret"
    assert client.model == "whisper-1"
    assert client.language == "de"


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
        },
    )
    request = RequestFactory().get("/", HTTP_HOST=site.hostname)

    client = VoxhelmClient.from_settings(request_or_site=request)

    assert client.api_base == "https://site.example/v1"
    assert client.api_key == "site-secret"


def test_require_setting_raises_when_missing(settings, monkeypatch):
    settings.CAST_VOXHELM_API_BASE = ""
    monkeypatch.delenv("CAST_VOXHELM_API_BASE", raising=False)

    with pytest.raises(ImproperlyConfigured, match="CAST_VOXHELM_API_BASE"):
        require_setting("CAST_VOXHELM_API_BASE")


def test_normalized_segments_falls_back_to_text():
    assert normalized_segments({"text": "Hello world"}) == [{"id": 0, "start": 0.0, "end": 0.0, "text": "Hello world"}]


def test_normalized_segments_ignores_invalid_entries_and_can_return_empty():
    assert normalized_segments({"segments": [None, {"text": "   "}, {"start": "bad", "text": "skip me"}]}) == []


def test_normalized_segments_handles_invalid_end_and_id():
    assert normalized_segments({"segments": [{"id": "not-an-int", "start": 1.25, "end": "bad", "text": "Hello"}]}) == [
        {"id": 0, "start": 1.25, "end": 1.25, "text": "Hello"}
    ]


def test_render_transcript_formats_from_verbose_json():
    payload = {
        "segments": [
            {
                "id": 1,
                "start": 0.62,
                "end": 5.16,
                "text": "Hello world",
            }
        ]
    }

    assert render_dote(payload) == {
        "lines": [
            {
                "startTime": "00:00:00,620",
                "endTime": "00:00:05,160",
                "speakerDesignation": "",
                "text": "Hello world",
            }
        ]
    }
    assert render_podlove(payload) == {
        "version": 1,
        "transcripts": [
            {
                "start": "00:00:00.620",
                "start_ms": 620,
                "end": "00:00:05.160",
                "end_ms": 5160,
                "speaker": "",
                "voice": "",
                "text": "Hello world",
            }
        ],
    }


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
        "output": {"formats": ["json", "vtt"]},
        "context": {"audio_id": 1},
        "task_ref": "cast-audio-1",
    }


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

    verbose_json = {
        "text": "Hello world",
        "segments": [
            {
                "id": 0,
                "start": 0.0,
                "end": 1.5,
                "text": "Hello world",
            }
        ],
    }

    class StubClient:
        def __init__(self):
            self.submit_calls = []

        def submit_transcription_job(self, *, source_url, task_ref, context):
            self.submit_calls.append((source_url, task_ref, context))
            return {"id": "job-1", "state": "succeeded", "result": {"artifacts": {"json": "/json", "vtt": "/vtt"}}}

        def wait_for_job(self, job_id):
            raise AssertionError(f"wait_for_job should not run for terminal jobs: {job_id}")

        def download_artifact(self, artifact_path):
            if artifact_path == "/json":
                return json.dumps(verbose_json).encode("utf-8")
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
                "speaker": "",
                "voice": "",
                "text": "Hello world",
            }
        ],
    }
    assert result.transcript.dote_data == {
        "lines": [
            {
                "startTime": "00:00:00,000",
                "endTime": "00:00:01,500",
                "speakerDesignation": "",
                "text": "Hello world",
            }
        ]
    }
    with result.transcript.vtt.open("r") as handle:
        assert handle.read() == "WEBVTT\n\n00:00:00.000 --> 00:00:01.500\nHello world\n"
    assert client.submit_calls == [
        (
            audio.m4a.url,
            f"cast-audio-{audio.pk}",
            {"consumer": "django-cast", "audio_id": audio.pk},
        )
    ]


def test_generate_for_audio_requires_saved_audio():
    class FakeAudio:
        pk = None

    with pytest.raises(VoxhelmError, match="must be saved"):
        VoxhelmTranscriptService(client=object()).generate_for_audio(FakeAudio())  # type: ignore[arg-type]


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
    verbose_json = {
        "text": "fresh transcript",
        "segments": [
            {
                "id": 1,
                "start": 2.0,
                "end": 4.0,
                "text": "fresh transcript",
            }
        ],
    }

    class StubClient:
        def submit_transcription_job(self, *, source_url, task_ref, context):
            assert source_url == audio.m4a.url
            assert task_ref == f"cast-audio-{audio.pk}"
            assert context == {"consumer": "django-cast", "audio_id": audio.pk}
            return {"id": "job-2", "state": "succeeded", "result": {"artifacts": {"json": "/json", "vtt": "/vtt"}}}

        def wait_for_job(self, job_id):
            raise AssertionError(f"wait_for_job should not run for terminal jobs: {job_id}")

        def download_artifact(self, artifact_path):
            if artifact_path == "/json":
                return json.dumps(verbose_json).encode("utf-8")
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
        def submit_transcription_job(self, *, source_url, task_ref, context):
            del source_url, task_ref, context
            return {"id": "job-3", "state": "queued"}

        def wait_for_job(self, job_id):
            assert job_id == "job-3"
            return {"id": "job-3", "state": "failed", "error": {"message": "transcription failed"}}

        def download_artifact(self, artifact_path):
            raise AssertionError(f"unexpected artifact: {artifact_path}")

    with pytest.raises(VoxhelmError, match="transcription failed"):
        VoxhelmTranscriptService(client=StubClient()).generate_for_audio(audio)


@pytest.mark.django_db
def test_generate_for_audio_rejects_non_object_json_artifact(settings, user, m4a_audio):
    settings.MEDIA_URL = "https://media.example.com/"
    audio = Audio(user=user, m4a=m4a_audio, title="episode")
    audio.save(duration=False, cache_file_sizes=False)

    class StubClient:
        def submit_transcription_job(self, *, source_url, task_ref, context):
            del source_url, task_ref, context
            return {"id": "job-4", "state": "succeeded", "result": {"artifacts": {"json": "/json", "vtt": "/vtt"}}}

        def wait_for_job(self, job_id):
            raise AssertionError(f"wait_for_job should not run for terminal jobs: {job_id}")

        def download_artifact(self, artifact_path):
            if artifact_path == "/json":
                return b'["not-an-object"]'
            return b"WEBVTT\n"

    with pytest.raises(VoxhelmError, match="not an object"):
        VoxhelmTranscriptService(client=StubClient()).generate_for_audio(audio)
