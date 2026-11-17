"""A committed admin media save stays reported as saved when search indexing fails."""

import logging

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from cast.models import Audio, Transcript, Video

CHOOSER_PREFIX = "media-chooser-upload"


class FailingBackend:
    def __init__(self) -> None:
        self.added: list = []

    def add(self, obj) -> None:
        self.added.append(obj)
        raise RuntimeError("synthetic backend unavailable")


class RecordingBackend:
    def __init__(self) -> None:
        self.added: list = []

    def add(self, obj) -> None:
        self.added.append(obj)


@pytest.fixture
def backends(mocker):
    failing, recording = FailingBackend(), RecordingBackend()
    mocker.patch("cast.views.media.get_search_backends", return_value=[failing, recording])
    return failing, recording


def queued_messages(response) -> list[tuple[str, str]]:
    return [(message.level_tag, str(message)) for message in get_messages(response.wsgi_request)]


def assert_index_failure_reported(response, caplog, obj, backends) -> None:
    failing, recording = backends
    assert failing.added == [obj]
    # The other configured backends are still attempted.
    assert recording.added == [obj]
    warnings = [text for level, text in queued_messages(response) if level == "warning"]
    assert any(
        "search index could not be updated" in text and "Do not save or upload it again" in text for text in warnings
    )
    assert any("Search index update failed" in record.getMessage() for record in caplog.records)


def assert_file_kept(field) -> None:
    assert field.name
    assert field.storage.exists(field.name)


@pytest.mark.django_db
def test_audio_add_reports_committed_save_after_index_failure(admin_client, m4a_audio, backends, caplog):
    caplog.set_level(logging.ERROR, logger="cast.views.media")

    response = admin_client.post(reverse("castaudio:add"), {"title": "Committed audio", "m4a": m4a_audio})

    assert response.status_code == 302
    assert response.url == reverse("castaudio:index")
    audio = Audio.objects.get(title="Committed audio")
    assert_file_kept(audio.m4a)
    assert_index_failure_reported(response, caplog, audio, backends)
    assert any(level == "success" and "added" in text for level, text in queued_messages(response))


@pytest.mark.django_db
def test_video_add_and_edit_report_committed_save_after_index_failure(admin_client, minimal_mp4, backends, caplog):
    caplog.set_level(logging.ERROR, logger="cast.views.media")

    response = admin_client.post(reverse("castvideo:add"), {"title": "Committed video", "original": minimal_mp4})

    assert response.status_code == 302
    video = Video.objects.get(title="Committed video")
    assert_file_kept(video.original)
    assert_index_failure_reported(response, caplog, video, backends)

    for backend in backends:
        backend.added.clear()
    caplog.clear()
    response = admin_client.post(reverse("castvideo:edit", args=(video.pk,)), {"title": "Edited video"})

    assert response.status_code == 302
    video.refresh_from_db()
    assert video.title == "Edited video"
    assert_file_kept(video.original)
    assert_index_failure_reported(response, caplog, video, backends)


@pytest.mark.django_db
def test_chooser_upload_returns_saved_object_after_index_failure(admin_client, minimal_mp4, backends, caplog):
    caplog.set_level(logging.ERROR, logger="cast.views.media")

    response = admin_client.post(
        reverse("castvideo:chooser_upload"),
        {f"{CHOOSER_PREFIX}-title": "Chosen video", f"{CHOOSER_PREFIX}-original": minimal_mp4},
    )

    assert response.status_code == 200
    video = Video.objects.get(title="Chosen video")
    assert response.json()["step"] == "video_chosen"
    assert response.json()["result"]["id"] == video.pk
    assert_file_kept(video.original)
    assert_index_failure_reported(response, caplog, video, backends)


@pytest.mark.django_db
def test_transcript_upload_and_edit_report_committed_save_after_index_failure(
    admin_client, audio, podlove_transcript, backends, caplog
):
    caplog.set_level(logging.ERROR, logger="cast.views.media")

    response = admin_client.post(
        reverse("cast-transcript:chooser_upload"),
        {f"{CHOOSER_PREFIX}-audio": audio.pk, f"{CHOOSER_PREFIX}-podlove": podlove_transcript},
    )

    assert response.status_code == 200
    transcript = Transcript.objects.get(audio=audio)
    assert response.json()["result"]["id"] == transcript.pk
    assert_file_kept(transcript.podlove)
    assert_index_failure_reported(response, caplog, transcript, backends)

    for backend in backends:
        backend.added.clear()
    caplog.clear()
    podlove_transcript.seek(0)
    response = admin_client.post(
        reverse("cast-transcript:edit", args=(transcript.pk,)),
        {"audio": audio.pk, "podlove": podlove_transcript},
    )

    assert response.status_code == 302
    transcript.refresh_from_db()
    assert_file_kept(transcript.podlove)
    assert_index_failure_reported(response, caplog, transcript, backends)


@pytest.mark.django_db
def test_unavailable_search_backends_do_not_fail_committed_save(admin_client, minimal_mp4, mocker, caplog):
    caplog.set_level(logging.ERROR, logger="cast.views.media")
    mocker.patch("cast.views.media.get_search_backends", side_effect=RuntimeError("synthetic misconfiguration"))

    response = admin_client.post(reverse("castvideo:add"), {"title": "Unindexed video", "original": minimal_mp4})

    assert response.status_code == 302
    assert Video.objects.filter(title="Unindexed video").exists()
    assert any("search index could not be updated" in text for _, text in queued_messages(response))
    assert any("Search backends unavailable" in record.getMessage() for record in caplog.records)


@pytest.mark.django_db
def test_successful_reindex_adds_no_warning(admin_client, minimal_mp4, mocker):
    recording = RecordingBackend()
    mocker.patch("cast.views.media.get_search_backends", return_value=[recording])

    response = admin_client.post(reverse("castvideo:add"), {"title": "Indexed video", "original": minimal_mp4})

    assert response.status_code == 302
    assert [obj.title for obj in recording.added] == ["Indexed video"]
    assert not [text for level, text in queued_messages(response) if level == "warning"]


@pytest.mark.django_db
def test_interruption_during_reindex_is_not_swallowed(admin_client, minimal_mp4, mocker):
    backend = mocker.Mock()
    backend.add.side_effect = KeyboardInterrupt
    mocker.patch("cast.views.media.get_search_backends", return_value=[backend])

    with pytest.raises(KeyboardInterrupt):
        admin_client.post(reverse("castvideo:add"), {"title": "Interrupted video", "original": minimal_mp4})


@pytest.mark.django_db
def test_inline_text_correction_reports_stale_index_in_response(admin_client, episode, mocker, caplog):
    from cast.transcripts import services
    from tests.transcripts.remaining_ux_test import passage_transcript

    caplog.set_level(logging.ERROR, logger="cast.views.media")
    transcript = passage_transcript(episode)
    failing, recording = FailingBackend(), RecordingBackend()
    mocker.patch("cast.views.media.get_search_backends", return_value=[failing, recording])

    response = admin_client.post(
        reverse("cast-transcript:preview", args=(transcript.pk,)),
        {
            "action": "correct-text",
            "start_ms": 0,
            "text": "Committed correction",
            "artifact_revision": services.artifact_revision(transcript),
        },
    )

    assert response.status_code == 200
    assert response.json()["search_index_updated"] is False
    transcript.refresh_from_db()
    assert transcript.plain_text == "Committed correction"
    assert recording.added == [transcript]
    assert any("Search index update failed" in record.getMessage() for record in caplog.records)

    # The preview page tells the editor about a stale index instead of a plain "Saved".
    page = admin_client.get(reverse("cast-transcript:preview", args=(transcript.pk,))).content.decode()
    assert "result.search_index_updated === false" in page
    assert "Saved, but the search index could not be updated" in page
