from django.urls import reverse

import pytest

from cast.models import Audio


class TestPostWithAudioDetail:
    pytestmark = pytest.mark.django_db

    def test_get_post_with_audio_detail(self, client, post_with_audio):
        audio = post_with_audio.audios.first()
        detail_url = post_with_audio.get_url()

        r = client.get(detail_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "html" in content

        # make sure audio title included in rendered audio block
        assert audio.title in content


def get_endpoint_urls_without_args():
    urls = {}
    view_names = ["index", "add", "chooser", "chooser_upload"]
    for view_name in view_names:
        audio_view_name = f"audio_{view_name}"
        urls[audio_view_name] = reverse(f"castmedia:{audio_view_name}")
    return urls


def get_endpoint_urls_with_args(audio):
    urls = {}
    view_names = ["edit", "delete", "chosen"]
    for view_name in view_names:
        audio_view_name = f"audio_{view_name}"
        urls[audio_view_name] = reverse(f"castmedia:{audio_view_name}", args=(audio.id,))
    return urls


class AudioUrls:
    def __init__(self, audio):
        self.audio = audio
        self.urls = get_endpoint_urls_without_args()
        self.urls.update(get_endpoint_urls_with_args(audio))

    def __getattr__(self, item):
        return self.urls[item]


@pytest.fixture
def audio_urls(audio):
    return AudioUrls(audio)


class TestAllAudioEndpoints:
    pytestmark = pytest.mark.django_db

    def test_get_all_not_authenticated(self, client, audio_urls):
        for view_name, url in audio_urls.urls.items():
            r = client.get(url)

            # redirect to login
            assert r.status_code == 302
            login_url = reverse("wagtailadmin_login")
            assert login_url in r.url

    def test_get_all_authenticated(self, authenticated_client, audio_urls):
        for view_name, url in audio_urls.urls.items():
            r = authenticated_client.get(url)

            # assert we are not redirected to login
            assert r.status_code == 200


class TestAudioIndex:
    pytestmark = pytest.mark.django_db

    def test_get_audio_index(self, authenticated_client, audio_urls):
        r = authenticated_client.get(audio_urls.audio_index)

        assert r.status_code == 200
        content = r.content.decode("utf-8")

        # make sure it's the media results page
        assert "html" in content
        assert "media-results" in content

        # make sure audio_urls.audio is included in results
        assert audio_urls.audio.title in content

    def test_get_audio_index_ajax(self, authenticated_client, audio_urls):
        headers = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
        r = authenticated_client.get(audio_urls.audio_index, **headers)

        assert r.status_code == 200
        content = r.content.decode("utf-8")

        # make sure it's the media results page
        assert "table" in content
        assert "listing" in content

        # make sure audio_urls.audio is included in results
        assert audio_urls.audio.title in content

    def test_get_audio_index_with_search(self, authenticated_client, audio_urls):
        r = authenticated_client.get(audio_urls.audio_index, {"q": audio_urls.audio.title})

        assert r.status_code == 200
        content = r.content.decode("utf-8")

        # make sure it's the media results page
        assert "html" in content
        assert "media-results" in content

        # make sure audio_urls.audio is included in results
        assert audio_urls.audio.title in content

    def test_get_audio_index_with_search_invalid(self, authenticated_client, audio_urls):
        r = authenticated_client.get(audio_urls.audio_index, {"q": " "})

        assert r.status_code == 200
        content = r.content.decode("utf-8")

        # make sure it's the media results page
        assert "html" in content
        assert "media-results" in content

        # make sure audio_urls.audio is included in results
        assert audio_urls.audio.title in content


class TestAudioAdd:
    pytestmark = pytest.mark.django_db

    def test_get_add_audio(self, authenticated_client, audio_urls):
        r = authenticated_client.get(audio_urls.audio_add)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Uploading…" in content

    def test_post_add_audio_invalid_form(self, authenticated_client):
        add_url = reverse("castmedia:audio_add")

        post_data = {
            "title": "foobar",
            "tags": "foo,bar,baz",
        }
        r = authenticated_client.post(add_url, post_data)

        # make sure we dont get redirected to audio_index
        assert r.status_code == 200

        # make sure we didn't create a audio
        Audio.objects.first() is None

    def test_post_add_audio(self, authenticated_client, minimal_mp4):
        add_url = reverse("castmedia:audio_add")

        post_data = {
            "title": "foobar",
            "tags": "foo,bar,baz",
            "original": minimal_mp4,
        }
        r = authenticated_client.post(add_url, post_data)

        # make sure we get redirected to audio_index
        assert r.status_code == 302
        assert r.url == reverse("castmedia:audio_index")

        # make sure field were saved correctly
        audio = Audio.objects.first()
        assert audio.title == post_data["title"]

        actual_tags = set([t.name for t in audio.tags.all()])
        expected_tags = set(post_data["tags"].split(","))
        assert actual_tags == expected_tags


class TestAudioEdit:
    pytestmark = pytest.mark.django_db

    def test_get_edit_audio(self, authenticated_client, audio_urls):
        r = authenticated_client.get(audio_urls.audio_edit)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Delete" in content

    def test_get_edit_audio_without_original(self, authenticated_client, audio_without_original):
        audio = audio_without_original
        edit_url = reverse("castmedia:audio_edit", args=(audio.id,))
        r = authenticated_client.get(edit_url)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Delete" in content

    def test_get_edit_audio_with_original_no_filesize(self, settings, authenticated_client, audio_without_file):
        settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
        audio = audio_without_file
        edit_url = reverse("castmedia:audio_edit", args=(audio.id,))
        r = authenticated_client.get(edit_url)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Delete" in content

    def test_post_edit_audio_invalid_form(self, authenticated_client, audio_urls):
        post_data = {"foo": "bar"}  # must not be empty because of if request.POST claus
        r = authenticated_client.post(audio_urls.audio_edit, post_data)

        # make sure we dont get redirected to audio_index
        assert r.status_code == 200

    def test_post_edit_audio_title(self, authenticated_client, audio_urls):
        audio = audio_urls.audio
        post_data = {
            "title": "changed title",
        }
        r = authenticated_client.post(audio_urls.audio_edit, post_data)

        # make sure we get redirected to audio_index
        assert r.status_code == 302
        assert r.url == audio_urls.audio_index

        # make sure title was changes
        audio.refresh_from_db()
        assert audio.title == post_data["title"]

    def test_post_edit_audio_original(self, authenticated_client, audio_urls, minimal_mp4):
        post_data = {
            "title": "asdf",
            "original": minimal_mp4,
        }
        r = authenticated_client.post(audio_urls.audio_edit, post_data)

        # make sure we get redirected to audio_index
        assert r.status_code == 302
        assert r.url == audio_urls.audio_index


class TestAudioDelete:
    pytestmark = pytest.mark.django_db

    def test_get_delete_audio(self, authenticated_client, audio_urls):
        r = authenticated_client.get(audio_urls.audio_delete)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Are you sure you want to delete this audio?" in content

    def test_post_delete_audio(self, authenticated_client, audio_urls):
        audio = audio_urls.audio
        # post data is necessary because of if request.POST
        r = authenticated_client.post(audio_urls.audio_delete, {"delete": "yes"})

        # make sure we get redirected to audio_index
        assert r.status_code == 302
        assert r.url == audio_urls.audio_index

        # make sure audio was deleted
        with pytest.raises(Audio.DoesNotExist):
            audio.refresh_from_db()


class TestAudioChosen:
    pytestmark = pytest.mark.django_db

    def test_get_chosen_audio_not_found(self, authenticated_client, audio_urls):
        audio = audio_urls.audio
        audio.delete()
        r = authenticated_client.get(audio_urls.audio_chosen)

        assert r.status_code == 404

    def test_get_chosen_audio_success(self, authenticated_client, audio_urls):
        audio = audio_urls.audio
        r = authenticated_client.get(audio_urls.audio_chosen)

        assert r.status_code == 200

        # make sure returned data belongs to the right audio instance
        data = r.json()
        assert data["result"]["title"] == audio.title


class TestAudioChooser:
    pytestmark = pytest.mark.django_db

    def test_get_audio_in_chooser(self, authenticated_client, audio_urls):
        audio = audio_urls.audio
        r = authenticated_client.get(audio_urls.audio_chooser)

        assert r.status_code == 200

        # make sure existing audio is in chooser
        content = r.content.decode("utf-8")
        assert audio.title in content

        # make sure prefix for form fields is set
        assert "media-chooser-upload" in content


class TestAudioChooserUpload:
    pytestmark = pytest.mark.django_db

    def test_get_audio_in_chooser_upload(self, authenticated_client, audio_urls):
        audio = audio_urls.audio
        r = authenticated_client.get(audio_urls.audio_chooser_upload)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert audio.title in content

    def test_post_upload_audio_form_invalid(self, authenticated_client):
        upload_url = reverse("castmedia:audio_chooser_upload")
        post_data = {"foo": "bar"}
        r = authenticated_client.post(upload_url, post_data)

        assert r.status_code == 200

        # make sure error is reported
        messages = list(r.context["messages"])
        assert len(messages) == 1
        assert "The audio could not be saved due to errors." == str(messages[0]).rstrip()

    def test_post_upload_audio(self, authenticated_client, minimal_mp4):
        upload_url = reverse("castmedia:audio_chooser_upload")
        prefix = "media-chooser-upload"
        post_data = {
            f"{prefix}-title": "foobar",
            f"{prefix}-tags": "foo,bar,baz",
            f"{prefix}-original": minimal_mp4,
        }
        r = authenticated_client.post(upload_url, post_data)

        assert r.status_code == 200

        # make sure field were saved correctly
        audio = Audio.objects.first()
        assert audio.title == post_data[f"{prefix}-title"]

        actual_tags = set([t.name for t in audio.tags.all()])
        expected_tags = set(post_data[f"{prefix}-tags"].split(","))
        assert actual_tags == expected_tags
