from unittest.mock import patch

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse

from cast.devdata import create_transcript
from cast.models import Transcript


def get_endpoint_urls_without_args():
    urls = {}
    view_names = ["index", "add", "chooser", "chooser_upload"]
    for view_name in view_names:
        urls[view_name] = reverse(f"cast-transcript:{view_name}")
    return urls


def get_endpoint_urls_with_args(transcript):
    urls = {}
    view_names = ["edit", "delete", "chosen"]
    for view_name in view_names:
        urls[view_name] = reverse(f"cast-transcript:{view_name}", args=(transcript.id,))
    return urls


class TranscriptUrls:
    def __init__(self, transcript):
        self.transcript = transcript
        self.urls = get_endpoint_urls_without_args()
        self.urls.update(get_endpoint_urls_with_args(transcript))

    def __getattr__(self, item):
        return self.urls[item]


@pytest.fixture
def transcript_urls(transcript):
    return TranscriptUrls(transcript)


class TestAllTranscriptEndpoints:
    pytestmark = pytest.mark.django_db

    def test_get_all_not_authenticated(self, client, transcript_urls):
        for view_name, url in transcript_urls.urls.items():
            r = client.get(url)

            # redirect to log in
            assert r.status_code == 302
            login_url = reverse("wagtailadmin_login")
            assert login_url in r.url

    def test_get_all_authenticated(self, authenticated_client, transcript_urls):
        for view_name, url in transcript_urls.urls.items():
            r = authenticated_client.get(url)

            # assert we are not redirected to log in
            assert r.status_code == 200


class TestTranscriptIndex:
    pytestmark = pytest.mark.django_db

    def test_get_index(self, authenticated_client, transcript_urls):
        r = authenticated_client.get(transcript_urls.index)

        assert r.status_code == 200
        content = r.content.decode("utf-8")

        # make sure it's the media results page
        assert "html" in content
        assert "media-results" in content

        assert transcript_urls.transcript.audio.title in content

    def test_get_index_ajax(self, authenticated_client, transcript_urls):
        headers = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
        r = authenticated_client.get(transcript_urls.index, **headers)

        assert r.status_code == 200
        content = r.content.decode("utf-8")

        # make sure it's the media results page
        assert "table" in content
        assert "listing" in content

        # make sure transcript_urls.transcript is included in results
        assert transcript_urls.transcript.audio.title in content

    def test_get_index_with_search(self, authenticated_client, transcript_urls):
        r = authenticated_client.get(transcript_urls.index, {"q": transcript_urls.transcript.audio.title})

        assert r.status_code == 200
        content = r.content.decode("utf-8")

        # make sure it's the media results page
        assert "html" in content
        assert "media-results" in content

        # make sure transcript_urls.transcript.audio is included in results
        assert transcript_urls.transcript.audio.title in content

    def test_get_index_with_search_invalid(self, authenticated_client, transcript_urls):
        r = authenticated_client.get(transcript_urls.index, {"q": " "})

        assert r.status_code == 200
        content = r.content.decode("utf-8")

        # make sure it's the media results page
        assert "html" in content
        assert "media-results" in content

        # make sure transcript_urls.transcript.audio is included in results
        assert transcript_urls.transcript.audio.title in content

    def test_get_index_with_pagination(self, authenticated_client, user, audio):
        transcript = Transcript(audio=audio)
        transcript.save()
        index_url = reverse("cast-transcript:index")
        with patch("cast.views.transcript.MENU_ITEM_PAGINATION", return_value=1):
            r = authenticated_client.get(index_url, {"p": "1"})
        transcripts = r.context["transcripts"]

        # make sure we got last transcript from first page
        assert len(transcripts) == 1
        assert transcripts[0] == transcripts[-1]

        with patch("cast.views.transcript.MENU_ITEM_PAGINATION", return_value=1):
            r = authenticated_client.get(index_url, {"p": "2"})
        transcripts = r.context["transcripts"]

        # make sure we got first transcript from last page
        assert len(transcripts) == 1
        assert transcripts[0] == transcripts[0]


class TestTranscriptAdd:
    pytestmark = pytest.mark.django_db

    def test_get_add_transcript(self, authenticated_client, transcript_urls):
        r = authenticated_client.get(transcript_urls.add)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Uploading…" in content

    def test_post_add_transcript_invalid_form(self, authenticated_client, podlove_transcript):
        podlove_transcript.seek(podlove_transcript.size)  # seek to end to make file empty/invalid
        add_url = reverse("cast-transcript:add")

        post_data = {
            "podlove": podlove_transcript,
            "tags": "foo,bar,baz",  # invalid
        }
        r = authenticated_client.post(add_url, post_data)

        # make sure we don't get redirected to index
        assert r.status_code == 200
        assert r.context["message"] == "The transcript file could not be saved due to errors."

        # make sure we didn't create an transcript
        assert Transcript.objects.first() is None

    def test_post_add_transcript(self, authenticated_client, audio, podlove_transcript):
        add_url = reverse("cast-transcript:add")

        post_data = {
            "podlove": podlove_transcript,
            "audio": audio.id,
        }
        r = authenticated_client.post(add_url, post_data)

        # make sure we get redirected to index
        assert r.status_code == 302
        assert r.url == reverse("cast-transcript:index")

        # make sure field were saved correctly
        transcript = Transcript.objects.first()
        with transcript.podlove.open("r") as file:
            saved_transcript_content = file.read()
        podlove_transcript.seek(0)
        submitted_transcript_content = podlove_transcript.read().decode("utf-8")
        assert saved_transcript_content == submitted_transcript_content


class TestTranscriptEdit:
    pytestmark = pytest.mark.django_db

    def test_get_edit_transcript(self, authenticated_client, transcript_urls):
        r = authenticated_client.get(transcript_urls.edit)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Delete" in content

    def test_get_edit_transcript_detail(self, authenticated_client, transcript):
        edit_url = reverse("cast-transcript:edit", args=(transcript.id,))
        r = authenticated_client.get(edit_url)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Delete" in content

    def test_post_edit_transcript_invalid_form(self, authenticated_client, transcript_urls, podlove_transcript):
        podlove_transcript.seek(podlove_transcript.size)  # seek to end to make file empty/invalid
        post_data = {"podlove": podlove_transcript}
        r = authenticated_client.post(transcript_urls.edit, post_data)

        # make sure we don't get redirected to index
        assert r.status_code == 200

    def test_post_edit_audio_podlove(self, authenticated_client, transcript_urls, podlove_transcript):
        audio = transcript_urls.transcript.audio
        post_data = {
            "podlove": podlove_transcript,
            "audio": audio.id,
        }
        r = authenticated_client.post(transcript_urls.edit, post_data)

        # make sure we get redirected to index
        assert r.status_code == 302
        assert r.url == transcript_urls.index

        # make sure transcript in podlove was changes
        transcript = transcript_urls.transcript
        transcript.refresh_from_db()

        with transcript.podlove.open("r") as file:
            saved_transcript_content = file.read()
        podlove_transcript.seek(0)
        submitted_transcript_content = podlove_transcript.read().decode("utf-8")
        assert saved_transcript_content == submitted_transcript_content


class TestTranscriptDelete:
    pytestmark = pytest.mark.django_db

    def test_get_delete_transcript(self, authenticated_client, transcript_urls):
        r = authenticated_client.get(transcript_urls.delete)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Are you sure you want to delete this transcript?" in content

    def test_post_delete_transcript(self, authenticated_client, transcript_urls):
        # post data is necessary because of if request.POST
        r = authenticated_client.post(transcript_urls.delete, {"delete": "yes"})

        # make sure we get redirected to index
        assert r.status_code == 302
        assert r.url == transcript_urls.index

        # make sure transcript was deleted
        transcript = transcript_urls.transcript
        with pytest.raises(Transcript.DoesNotExist):
            transcript.refresh_from_db()


class TestTranscriptChosen:
    pytestmark = pytest.mark.django_db

    def test_get_chosen_transcript_not_found(self, authenticated_client, transcript_urls):
        transcript_urls.transcript.delete()
        r = authenticated_client.get(transcript_urls.chosen)

        assert r.status_code == 404

    def test_get_chosen_transcript_success(self, authenticated_client, transcript_urls):
        r = authenticated_client.get(transcript_urls.chosen)

        assert r.status_code == 200

        # make sure returned data belongs to the right transcript instance
        data = r.json()
        assert data["result"]["id"] == transcript_urls.transcript.id


class TestTranscriptChooser:
    pytestmark = pytest.mark.django_db

    def test_get_transcript_in_chooser(self, authenticated_client, transcript_urls):
        audio = transcript_urls.transcript.audio
        r = authenticated_client.get(transcript_urls.chooser)

        assert r.status_code == 200

        # make sure existing transcript is in chooser
        content = r.content.decode("utf-8")
        assert audio.title in content

        # make sure prefix for form fields is set
        assert "media-chooser-upload" in content

    def test_get_chooser_with_search(self, authenticated_client, transcript_urls):
        r = authenticated_client.get(transcript_urls.chooser, {"q": transcript_urls.transcript.audio.title})

        assert r.status_code == 200

        # make sure searched transcript is included in results
        assert r.context["transcripts"][0] == transcript_urls.transcript

    def test_get_chooser_with_search_invalid(self, authenticated_client, transcript_urls):
        # {"p": "1"} (page 1) leads to the search form being invalid
        r = authenticated_client.get(transcript_urls.chooser, {"p": "1"})

        assert r.status_code == 200

        # make sure searched transcripts is included in results
        assert r.context["transcripts"][0] == transcript_urls.transcript


class TestTranscriptChooserUpload:
    pytestmark = pytest.mark.django_db

    def test_get_transcript_in_chooser_upload(self, authenticated_client, transcript_urls):
        audio = transcript_urls.transcript.audio
        r = authenticated_client.get(transcript_urls.chooser_upload)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert audio.title in content

    def test_post_upload_transcript_form_invalid(self, authenticated_client, podlove_transcript):
        podlove_transcript.seek(podlove_transcript.size)  # seek to end to make file empty/invalid
        upload_url = reverse("cast-transcript:chooser_upload")
        post_data = {"media-chooser-podlove": podlove_transcript}
        r = authenticated_client.post(upload_url, post_data)

        assert r.status_code == 200
        assert r.context["message"] == "The transcript could not be saved due to errors."

    def test_post_upload_transcript(self, authenticated_client, podlove_transcript, settings, audio):
        settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
        upload_url = reverse("cast-transcript:chooser_upload")
        prefix = "media-chooser-upload"
        post_data = {
            f"{prefix}-audio": audio.id,
            f"{prefix}-podlove": podlove_transcript,
        }
        r = authenticated_client.post(upload_url, post_data)

        assert r.status_code == 200

        # make sure field was saved correctly
        transcript = Transcript.objects.first()
        with transcript.podlove.open("r") as file:
            saved_transcript_content = file.read()
        podlove_transcript.seek(0)
        submitted_transcript_content = podlove_transcript.read().decode("utf-8")
        assert saved_transcript_content == submitted_transcript_content

        # teardown
        transcript.podlove.delete()


class TestGetTranscriptAsJson:
    pytestmark = pytest.mark.django_db

    def test_get_transcript_as_json_not_found(self, client):
        url = reverse("cast:podlove-transcript-json", kwargs={"pk": 1})
        r = client.get(url)
        assert r.status_code == 404

    def test_get_transcript_as_json_no_podlove(self, client):
        # Given a transcript without a podlove file
        transcript = create_transcript()

        # When we request the transcript as JSON
        url = reverse("cast:podlove-transcript-json", kwargs={"pk": transcript.id})
        r = client.get(url)

        # Then we get a 404 response with an error message
        assert r.status_code == 404
        assert r.content.decode("utf-8") == "Podlove file not available"

    def test_get_transcript_as_json_not_valid_json(self, client):
        # Given a transcript that is not valid JSON
        transcript = create_transcript()
        transcript.podlove.save("podlove.json", ContentFile("not valid json"))
        transcript.save()

        # When we request the transcript as JSON
        url = reverse("cast:podlove-transcript-json", kwargs={"pk": transcript.id})
        r = client.get(url)

        # Then we get a 400 response with an error message
        assert r.status_code == 400
        assert r.content.decode("utf-8") == "Invalid JSON format in podlove file"

    def test_get_transcript_as_json_success(self, client):
        # Given a transcript in podlove format
        podlove = {
            "transcripts": [
                {
                    "start": "00:00:00.620",
                    "start_ms": 620,
                    "end": "00:00:05.160",
                    "end_ms": 5160,
                    "speaker": "",
                    "voice": "",
                    "text": "Ja, hallo liebe Hörerinnen und Hörer. Willkommen beim Python-Podcast der 5ten Episode.",
                }
            ]
        }
        transcript = create_transcript(podlove=podlove)

        # When we request the transcript as JSON
        url = reverse("cast:podlove-transcript-json", kwargs={"pk": transcript.id})
        r = client.get(url)
        assert r.status_code == 200

        # Then we get the transcript in the expected format
        assert r.json()["transcripts"] == podlove["transcripts"]


class TestGetTranscriptAsPodcastIndexJson:
    pytestmark = pytest.mark.django_db

    def test_get_transcript_as_json_not_found(self, client):
        url = reverse("cast:podcastindex-transcript-json", kwargs={"pk": 1})
        r = client.get(url)
        assert r.status_code == 404

    def test_get_transcript_as_json_no_dote(self, client):
        # Given a transcript without a dote file
        transcript = create_transcript()

        # When we request the transcript as JSON
        url = reverse("cast:podcastindex-transcript-json", kwargs={"pk": transcript.id})
        r = client.get(url)

        # Then we get a 404 response with an error message
        assert r.status_code == 404
        assert r.content.decode("utf-8") == "podcastindex JSON file not available"

    def test_get_transcript_as_json_not_valid_json(self, client):
        # Given a transcript that is not valid JSON
        transcript = create_transcript()
        transcript.dote.save("dote.json", ContentFile("not valid json"))
        transcript.save()

        # When we request the transcript as JSON
        url = reverse("cast:podcastindex-transcript-json", kwargs={"pk": transcript.id})
        r = client.get(url)

        # Then we get a 400 response with an error message
        assert r.status_code == 400
        assert r.content.decode("utf-8") == "Invalid JSON format in dote file"

    def test_get_transcript_as_json_success(self, client):
        # Given a transcript in podlove format
        dote = {
            "lines": [
                {
                    "startTime": "00:00:00,620",
                    "endTime": "00:00:05,160",
                    "speakerDesignation": "speaker",
                    "text": "Ja, hallo liebe Hörerinnen und Hörer. Willkommen beim Python-Podcast der 5ten Episode.",
                }
            ]
        }
        transcript = create_transcript(dote=dote)

        # When we request the transcript as JSON
        url = reverse("cast:podcastindex-transcript-json", kwargs={"pk": transcript.id})
        r = client.get(url)
        assert r.status_code == 200

        # Then we get the transcript in the expected format
        assert r.json() == {
            "version": "1.0",
            "segments": [
                {
                    "startTime": 0.62,
                    "endTime": 5.16,
                    "speaker": "speaker",
                    "body": "Ja, hallo liebe Hörerinnen und Hörer. Willkommen beim Python-Podcast der 5ten Episode.",
                },
            ],
        }


class TestGetTranscriptAsWebVtt:
    pytestmark = pytest.mark.django_db

    def test_get_transcript_as_vtt_not_found(self, client):
        url = reverse("cast:webvtt-transcript", kwargs={"pk": 1})
        r = client.get(url)
        assert r.status_code == 404

    def test_get_transcript_as_json_no_vtt(self, client):
        # Given a transcript without a vtt file
        transcript = create_transcript()

        # When we request the transcript as JSON
        url = reverse("cast:webvtt-transcript", kwargs={"pk": transcript.id})
        r = client.get(url)

        # Then we get a 404 response with an error message
        assert r.status_code == 404
        assert r.content.decode("utf-8") == "WebVTT file not available"

    def test_get_transcript_as_vtt_success(self, client):
        # Given a transcript in vtt format
        vtt = "WEBVTT\n\n00:00:00.620 --> 00:00:05.160\nJa, hallo liebe Hörerinnen und Hörer."
        transcript = create_transcript(vtt=vtt)

        # When we request the transcript as JSON
        url = reverse("cast:webvtt-transcript", kwargs={"pk": transcript.id})
        r = client.get(url)
        assert r.status_code == 200

        # Then we get the transcript in the expected format
        content = r.content.decode("utf-8")
        assert content == vtt


@pytest.fixture
def transcript_with_podlove():
    podlove = {
        "transcripts": [
            {
                "start": "00:00:00.620",
                "start_ms": 620,
                "end": "00:00:05.160",
                "end_ms": 5160,
                "speaker": "",
                "voice": "",
                "text": "Ja, hallo liebe Hörerinnen und Hörer. Willkommen beim Python-Podcast der 5ten Episode.",
            }
        ]
    }
    return create_transcript(podlove=podlove)


class TestGetTranscriptAsHtml:
    pytestmark = pytest.mark.django_db

    def test_get_transcript_as_html_not_found(self, client):
        url = reverse("cast:html-transcript-no-post", kwargs={"transcript_pk": 1})
        r = client.get(url)
        assert r.status_code == 404

    def test_get_transcript_as_html_no_podlove(self, client):
        transcript = create_transcript()
        url = reverse("cast:html-transcript-no-post", kwargs={"transcript_pk": transcript.pk})
        r = client.get(url)
        assert r.status_code == 404

    def test_get_transcript_as_html_broken_json(self, client):
        # Given a transcript that is not valid JSON
        transcript = create_transcript()
        transcript.podlove.save("podlove.json", ContentFile("not valid json"))
        transcript.save()

        # When we request the transcript as JSON
        url = reverse("cast:html-transcript-no-post", kwargs={"transcript_pk": transcript.id})
        r = client.get(url)

        # Then we get a 400 response with an error message
        assert r.status_code == 400
        assert r.content.decode("utf-8") == "Invalid JSON format in podlove file"

    def test_get_transcript_as_html_success(self, client, transcript_with_podlove):
        # Given a transcript in podlove format
        transcript = transcript_with_podlove

        # When we request the transcript as HTML
        url = reverse("cast:html-transcript-no-post", kwargs={"transcript_pk": transcript.id})
        r = client.get(url)
        assert r.status_code == 200

        # Then we get the transcript in the expected format
        content = r.content.decode("utf-8")
        assert "hallo liebe Hörerinnen und Hörer" in content

    def test_get_transcript_as_html_success_from_post(self, client, transcript_with_podlove, post):
        # Given a transcript in podlove format
        transcript = transcript_with_podlove

        # When we request the transcript as HTML
        url = reverse("cast:html-transcript", kwargs={"transcript_pk": transcript.id, "post_pk": post.id})
        r = client.get(url)
        assert r.status_code == 200

        # Then we get the transcript in the expected format
        content = r.content.decode("utf-8")
        assert "hallo liebe Hörerinnen und Hörer" in content

    def test_get_transcript_as_html_redirects_for_episode(self, client, episode):
        podlove = {
            "transcripts": [
                {
                    "start": "00:00:00.620",
                    "end": "00:00:05.160",
                    "speaker": "Host",
                    "text": "Hallo und willkommen.",
                }
            ]
        }
        transcript = create_transcript(audio=episode.podcast_audio, podlove=podlove)
        url = reverse("cast:html-transcript", kwargs={"transcript_pk": transcript.id, "post_pk": episode.id})

        r = client.get(url)

        assert r.status_code == 302
        assert r.url == reverse(
            "cast:episode-transcript",
            kwargs={"blog_slug": episode.blog.slug, "episode_slug": episode.slug},
        )

    def test_get_transcript_as_html_canonical_success(self, client, episode):
        podlove = {
            "transcripts": [
                {
                    "start": "00:00:00.620",
                    "end": "00:00:05.160",
                    "speaker": "Host",
                    "text": "Hallo und willkommen.",
                }
            ]
        }
        create_transcript(audio=episode.podcast_audio, podlove=podlove)
        url = reverse("cast:episode-transcript", kwargs={"blog_slug": episode.blog.slug, "episode_slug": episode.slug})

        r = client.get(url)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Hallo und willkommen." in content
        assert "Host" in content
        assert episode.title in content
        assert episode.get_url() in content

    def test_get_transcript_as_html_canonical_without_transcript(self, client, episode):
        url = reverse("cast:episode-transcript", kwargs={"blog_slug": episode.blog.slug, "episode_slug": episode.slug})

        r = client.get(url)

        assert r.status_code == 404

    def test_get_transcript_as_html_canonical_mismatched_blog(self, client, episode, blog):
        url = reverse("cast:episode-transcript", kwargs={"blog_slug": blog.slug, "episode_slug": episode.slug})

        r = client.get(url)

        assert r.status_code == 404
