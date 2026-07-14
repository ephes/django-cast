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


def test_validate_transcript_artifacts_accepts_valid_artifacts():
    validate_transcript_artifacts(
        podlove=VALID_PODLOVE_ARTIFACT,
        dote=VALID_DOTE_ARTIFACT,
        vtt=VALID_VTT_ARTIFACT,
        speakers=b'{"segments": []}',
    )


@pytest.mark.parametrize(
    ("artifacts", "message"),
    [
        ({"podlove": b"\xff"}, "podlove artifact was not valid UTF-8 JSON"),
        ({"podlove": b"[]"}, "podlove artifact must be a JSON object"),
        ({"podlove": b'{"transcripts": {}}'}, "podlove artifact must include a 'transcripts' list"),
        ({"dote": b'{"lines": ["bad"]}'}, "dote artifact lines must be JSON objects"),
        ({"dote": b'{"lines": [{"text": "done"}]}'}, "dote artifact lines must include keys"),
        ({"vtt": b"\xff"}, "vtt artifact was not valid UTF-8 text"),
        ({"vtt": b"not vtt"}, "vtt artifact must start with the WEBVTT header"),
        ({"speakers": b"[]"}, "speakers artifact must be a JSON object"),
    ],
)
def test_validate_transcript_artifacts_rejects_malformed_artifacts(artifacts, message):
    artifact_kwargs = {
        "podlove": VALID_PODLOVE_ARTIFACT,
        "dote": VALID_DOTE_ARTIFACT,
        "vtt": VALID_VTT_ARTIFACT,
        "speakers": None,
    }
    artifact_kwargs.update(artifacts)

    with pytest.raises(VoxhelmError, match=message):
        validate_transcript_artifacts(**artifact_kwargs)


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


def test_resolve_audio_task_ref_normalizes_explicit_refs():
    assert ensure_diarized_task_ref("cast-audio-1") == "cast-audio-1-diarized"
    assert ensure_diarized_task_ref("cast-audio-1-diarized-3-speakers") == "cast-audio-1-diarized-3-speakers"
    assert strip_diarized_task_ref("cast-audio-1-diarized-3-speakers") == "cast-audio-1"
    assert (
        resolve_audio_task_ref(
            1,
            task_ref="cast-audio-1-force",
            diarization_enabled=True,
            diarization_speaker_count=3,
        )
        == "cast-audio-1-force-diarized-3-speakers"
    )
    assert (
        resolve_audio_task_ref(
            1,
            task_ref="cast-audio-1-force-diarized-3-speakers",
            diarization_enabled=False,
        )
        == "cast-audio-1-force"
    )


@pytest.mark.django_db
def test_resolve_audio_diarization_enabled_honors_audio_mode(audio):
    client = SimpleNamespace(diarization_enabled=False)

    assert resolve_audio_diarization_enabled(audio, client) is False

    audio.transcript_diarization_mode = Audio.TranscriptDiarizationMode.ENABLED
    assert resolve_audio_diarization_enabled(audio, client) is True

    client.diarization_enabled = True
    audio.transcript_diarization_mode = Audio.TranscriptDiarizationMode.DISABLED
    assert resolve_audio_diarization_enabled(audio, client) is False

    audio.transcript_diarization_mode = Audio.TranscriptDiarizationMode.INHERIT
    assert resolve_audio_diarization_enabled(audio, client) is True


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


def test_read_response_bytes_without_limit_reads_all():
    assert read_response_bytes(FakeResponse(b"payload")) == b"payload"


def test_resolve_diarization_speaker_count_without_episode_manager():
    assert resolve_diarization_speaker_count(SimpleNamespace()) is None


def test_client_submit_job_and_download_artifact(mocker):
    requests = []

    def fake_open_url(request, *, timeout, follow_redirects=True):
        requests.append((request, timeout, follow_redirects))
        if request.full_url.endswith("/v1/jobs"):
            return FakeResponse(b'{"id": "job-1", "state": "queued"}')
        return FakeResponse(b"artifact-bytes")

    mocker.patch("cast.voxhelm.client.open_url", side_effect=fake_open_url)
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
    assert requests[0][2] is False
    assert requests[1][2] is False
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


def test_client_submit_job_diarization_override_controls_payload(mocker):
    enabled_client = VoxhelmClient(api_base="https://voxhelm.example", api_key="secret", diarization_enabled=True)
    enabled_request_json = mocker.patch.object(enabled_client, "request_json", return_value={"id": "job-1"})

    enabled_client.submit_transcription_job(
        source_url="https://media.example.com/episode.mp3",
        task_ref="cast-audio-1",
        context={"audio_id": 1},
        diarization_enabled=False,
    )

    assert "diarization" not in enabled_request_json.call_args.kwargs["payload"]

    disabled_client = VoxhelmClient(api_base="https://voxhelm.example", api_key="secret", diarization_enabled=False)
    disabled_request_json = mocker.patch.object(disabled_client, "request_json", return_value={"id": "job-2"})

    disabled_client.submit_transcription_job(
        source_url="https://media.example.com/episode.mp3",
        task_ref="cast-audio-1-diarized",
        context={"audio_id": 1},
        diarization_enabled=True,
    )

    assert disabled_request_json.call_args.kwargs["payload"]["diarization"] == {"enabled": True}


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


def test_client_request_bytes_omits_auth_for_cross_origin_url(mocker):
    requests = []

    def fake_open_url(request, *, timeout, follow_redirects=True):
        requests.append(request)
        return FakeResponse(b"{}")

    mocker.patch("cast.voxhelm.client.open_url", side_effect=fake_open_url)
    client = VoxhelmClient(api_base="https://voxhelm.example", api_key="secret")

    assert client.request_bytes(method="POST", path="https://api.other.example/jobs", payload={"ok": True}) == b"{}"

    request = requests[0]
    assert request.get_header("Authorization") is None
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data.decode("utf-8")) == {"ok": True}


def test_client_download_artifact_rejects_cross_origin_absolute_url(mocker):
    open_url_mock = mocker.patch("cast.voxhelm.client.open_url")
    client = VoxhelmClient(api_base="https://voxhelm.example", api_key="secret")

    with pytest.raises(VoxhelmError, match="configured Voxhelm origin"):
        client.download_artifact("https://cdn.example.com/transcripts/job-1.vtt")

    open_url_mock.assert_not_called()


def test_client_download_artifact_allows_same_origin_absolute_url(mocker):
    requests = []

    def fake_open_url(request, *, timeout, follow_redirects=True):
        requests.append((request, timeout, follow_redirects))
        return FakeResponse(b"artifact-bytes")

    mocker.patch("cast.voxhelm.client.open_url", side_effect=fake_open_url)
    client = VoxhelmClient(api_base="https://voxhelm.example", api_key="secret")

    artifact = client.download_artifact("https://voxhelm.example/v1/jobs/job-1/artifacts/transcript.vtt")

    assert artifact == b"artifact-bytes"
    assert requests[0][0].headers["Authorization"] == "Bearer secret"
    assert requests[0][2] is False


def test_client_download_artifact_rejects_oversized_response(mocker):
    mocker.patch("cast.voxhelm.client.MAX_VOXHELM_ARTIFACT_BYTES", 4)
    mocker.patch("cast.voxhelm.client.open_url", return_value=FakeResponse(b"12345"))
    client = VoxhelmClient(api_base="https://voxhelm.example", api_key="secret")

    with pytest.raises(VoxhelmError, match="maximum size"):
        client.download_artifact("/v1/jobs/job-1/artifacts/transcript.vtt")


def test_client_download_artifact_allows_response_at_size_limit(mocker):
    mocker.patch("cast.voxhelm.client.MAX_VOXHELM_ARTIFACT_BYTES", 4)
    mocker.patch("cast.voxhelm.client.open_url", return_value=FakeResponse(b"1234"))
    client = VoxhelmClient(api_base="https://voxhelm.example", api_key="secret")

    assert client.download_artifact("/v1/jobs/job-1/artifacts/transcript.vtt") == b"1234"


def test_client_download_artifact_rejects_redirect_response(mocker):
    error = HTTPError(
        url="https://voxhelm.example/v1/jobs/job-1/artifacts/transcript.vtt",
        code=302,
        msg="Found",
        hdrs=None,
        fp=io.BytesIO(b"redirect"),
    )
    open_url_mock = mocker.patch("cast.voxhelm.client.open_url", side_effect=error)
    client = VoxhelmClient(api_base="https://voxhelm.example", api_key="secret")

    with pytest.raises(VoxhelmError, match="302: redirect"):
        client.download_artifact("/v1/jobs/job-1/artifacts/transcript.vtt")

    assert open_url_mock.call_args.kwargs["follow_redirects"] is False


def test_open_url_without_redirects_uses_no_redirect_opener(mocker):
    opener = mocker.Mock()
    opener.open.return_value = FakeResponse(b"ok")
    build_opener = mocker.patch("cast.voxhelm.client.build_opener", return_value=opener)
    request = Request("https://voxhelm.example/v1/jobs")

    response = open_url(request, timeout=1.0, follow_redirects=False)

    assert response.read() == b"ok"
    assert build_opener.call_args.args == (NoRedirectHandler,)
    opener.open.assert_called_once_with(request, timeout=1.0)


def test_no_redirect_handler_blocks_redirect():
    handler = NoRedirectHandler()

    assert handler.redirect_request(None, None, 302, "Found", {}, "https://voxhelm.example/next") is None


def test_client_request_json_requires_object_response(mocker):
    mocker.patch("cast.voxhelm.client.open_url", return_value=FakeResponse(b'["not-an-object"]'))
    client = VoxhelmClient(api_base="https://voxhelm.example", api_key="secret")

    with pytest.raises(VoxhelmError, match="non-object"):
        client.request_json(method="GET", path="jobs/job-1")


def test_client_request_json_rejects_oversized_response(mocker):
    mocker.patch("cast.voxhelm.client.MAX_VOXHELM_API_RESPONSE_BYTES", 4)
    mocker.patch("cast.voxhelm.client.open_url", return_value=FakeResponse(b'{"id": "job-1"}'))
    client = VoxhelmClient(api_base="https://voxhelm.example", api_key="secret")

    with pytest.raises(VoxhelmError, match="maximum size"):
        client.request_json(method="GET", path="jobs/job-1")


def test_client_request_json_rejects_redirect_response(mocker):
    error = HTTPError(
        url="https://voxhelm.example/v1/jobs/job-1",
        code=302,
        msg="Found",
        hdrs=None,
        fp=io.BytesIO(b"redirect"),
    )
    open_url_mock = mocker.patch("cast.voxhelm.client.open_url", side_effect=error)
    client = VoxhelmClient(api_base="https://voxhelm.example", api_key="secret")

    with pytest.raises(VoxhelmError, match="302: redirect"):
        client.request_json(method="GET", path="jobs/job-1")

    assert open_url_mock.call_args.kwargs["follow_redirects"] is False


def test_client_http_error_includes_body(mocker):
    error = HTTPError(
        url="https://voxhelm.example/v1/jobs",
        code=502,
        msg="Bad Gateway",
        hdrs=None,
        fp=io.BytesIO(b"upstream broke"),
    )
    mocker.patch("cast.voxhelm.client.urlopen", side_effect=error)
    client = VoxhelmClient(api_base="https://voxhelm.example", api_key="secret")

    with pytest.raises(VoxhelmError, match="502: upstream broke"):
        client.request_bytes(method="GET", path="jobs/job-1")


def test_client_http_error_body_is_bounded(mocker):
    mocker.patch("cast.voxhelm.client.MAX_VOXHELM_ERROR_BYTES", 4)
    error = HTTPError(
        url="https://voxhelm.example/v1/jobs",
        code=500,
        msg="Server Error",
        hdrs=None,
        fp=io.BytesIO(b"abcdef"),
    )
    mocker.patch("cast.voxhelm.client.urlopen", side_effect=error)
    client = VoxhelmClient(api_base="https://voxhelm.example", api_key="secret")

    with pytest.raises(VoxhelmError, match=r"500: abcd \[truncated\]"):
        client.request_bytes(method="GET", path="jobs/job-1")


def test_client_http_error_falls_back_to_reason_when_body_is_empty(mocker):
    error = HTTPError(
        url="https://voxhelm.example/v1/jobs",
        code=503,
        msg="Service Unavailable",
        hdrs=None,
        fp=io.BytesIO(b""),
    )
    mocker.patch("cast.voxhelm.client.urlopen", side_effect=error)
    client = VoxhelmClient(api_base="https://voxhelm.example", api_key="secret")

    with pytest.raises(VoxhelmError, match="503: Service Unavailable"):
        client.request_bytes(method="GET", path="jobs/job-1")


def test_client_url_error_is_wrapped(mocker):
    mocker.patch("cast.voxhelm.client.urlopen", side_effect=URLError("offline"))
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


def test_client_submit_job_rejects_non_bool_diarization_override():
    client = VoxhelmClient(api_base="https://voxhelm.example", api_key="secret")

    with pytest.raises(TypeError, match="diarization_enabled must be a bool"):
        client.submit_transcription_job(
            source_url="https://media.example.com/episode.mp3",
            task_ref="cast-audio-1",
            context={"audio_id": 1},
            diarization_enabled="false",  # type: ignore[arg-type]
        )


def test_client_wait_for_job_times_out(mocker):
    client = VoxhelmClient(
        api_base="https://voxhelm.example",
        api_key="secret",
        poll_interval_seconds=0.0,
        job_timeout_seconds=5.0,
    )
    mocker.patch.object(client, "get_job", return_value={"id": "job-1", "state": "queued"})
    mocker.patch("cast.voxhelm.client.monotonic", side_effect=[0.0, 5.1])
    mocker.patch("cast.voxhelm.client.sleep")

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
    sleep_mock = mocker.patch("cast.voxhelm.client.sleep")

    assert client.wait_for_job("job-1") == {"id": "job-1", "state": "succeeded"}
    assert get_job.call_count == 2
    sleep_mock.assert_called_once_with(0.0)
