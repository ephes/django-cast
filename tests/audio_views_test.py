from unittest.mock import patch

import pytest
from django.urls import reverse

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

        # make sure audio is included in rendered audio block
        assert "block-audio" in content
        assert f"audio_{audio.pk}" in content


def get_endpoint_urls_without_args():
    urls = {}
    view_names = ["index", "add", "chooser", "chooser_upload"]
    for view_name in view_names:
        urls[view_name] = reverse(f"castaudio:{view_name}")
    return urls


def get_endpoint_urls_with_args(audio):
    urls = {}
    view_names = ["edit", "delete", "chosen"]
    for view_name in view_names:
        urls[view_name] = reverse(f"castaudio:{view_name}", args=(audio.id,))
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

            # redirect to log in
            assert r.status_code == 302
            login_url = reverse("wagtailadmin_login")
            assert login_url in r.url

    def test_get_all_authenticated(self, authenticated_client, audio_urls):
        for view_name, url in audio_urls.urls.items():
            r = authenticated_client.get(url)

            # assert we are not redirected to log in
            assert r.status_code == 200


class TestAudioIndex:
    pytestmark = pytest.mark.django_db

    def test_get_index(self, authenticated_client, audio_urls):
        r = authenticated_client.get(audio_urls.index)

        assert r.status_code == 200
        content = r.content.decode("utf-8")

        # make sure it's the media results page
        assert "html" in content
        assert "media-results" in content

        # make sure audio_urls.audio is included in results
        assert audio_urls.audio.title in content

    def test_get_index_ajax(self, authenticated_client, audio_urls):
        headers = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
        r = authenticated_client.get(audio_urls.index, **headers)

        assert r.status_code == 200
        content = r.content.decode("utf-8")

        # make sure it's the media results page
        assert "table" in content
        assert "listing" in content

        # make sure audio_urls.audio is included in results
        assert audio_urls.audio.title in content

    def test_get_index_with_search(self, authenticated_client, audio_urls):
        r = authenticated_client.get(audio_urls.index, {"q": audio_urls.audio.title})

        assert r.status_code == 200
        content = r.content.decode("utf-8")

        # make sure it's the media results page
        assert "html" in content
        assert "media-results" in content

        # make sure audio_urls.audio is included in results
        assert audio_urls.audio.title in content

    def test_get_index_with_search_invalid(self, authenticated_client, audio_urls):
        r = authenticated_client.get(audio_urls.index, {"q": " "})

        assert r.status_code == 200
        content = r.content.decode("utf-8")

        # make sure it's the media results page
        assert "html" in content
        assert "media-results" in content

        # make sure audio_urls.audio is included in results
        assert audio_urls.audio.title in content

    def test_get_index_with_pagination(self, authenticated_client, user):
        audio_models = []
        for i in range(1, 3):
            audio = Audio(user=user, title=f"audio {i}")
            audio.save()
            audio_models.append(audio)
        index_url = reverse("castaudio:index")
        with patch("cast.views.audio.MENU_ITEM_PAGINATION", return_value=1):
            r = authenticated_client.get(index_url, {"p": "1"})
        audios = r.context["audios"]

        # make sure we got last audio from first page
        assert len(audios) == 1
        assert audios[0] == audio_models[-1]

        with patch("cast.views.audio.MENU_ITEM_PAGINATION", return_value=1):
            r = authenticated_client.get(index_url, {"p": "2"})
        audios = r.context["audios"]

        # make sure we got first audio from last page
        assert len(audios) == 1
        assert audios[0] == audio_models[0]


class TestAudioAdd:
    pytestmark = pytest.mark.django_db

    def test_get_add_audio(self, authenticated_client, audio_urls):
        r = authenticated_client.get(audio_urls.add)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Uploading…" in content

    def test_post_add_audio_invalid_form(self, authenticated_client, m4a_audio):
        m4a_audio.seek(m4a_audio.size)  # seek to end to make file empty/invalid
        add_url = reverse("castaudio:add")

        post_data = {
            "title": "foobar",
            "m4a": m4a_audio,  # invalid
            "tags": "foo,bar,baz",
        }
        r = authenticated_client.post(add_url, post_data)

        # make sure we don't get redirected to index
        assert r.status_code == 200
        assert r.context["message"] == "The audio file could not be saved due to errors."

        # make sure we didn't create an audio
        assert Audio.objects.first() is None

    def test_post_add_audio(self, authenticated_client, minimal_mp4):
        add_url = reverse("castaudio:add")

        post_data = {
            "title": "foobar",
            "tags": "foo,bar,baz",
            "original": minimal_mp4,
        }
        r = authenticated_client.post(add_url, post_data)

        # make sure we get redirected to index
        assert r.status_code == 302
        assert r.url == reverse("castaudio:index")

        # make sure field were saved correctly
        audio = Audio.objects.first()
        assert audio.title == post_data["title"]

        actual_tags = {t.name for t in audio.tags.all()}
        expected_tags = set(post_data["tags"].split(","))
        assert actual_tags == expected_tags


class TestAudioEdit:
    pytestmark = pytest.mark.django_db

    def test_get_edit_audio(self, authenticated_client, audio_urls):
        r = authenticated_client.get(audio_urls.edit)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Delete" in content

    def test_get_edit_audio_without_m4a(self, authenticated_client, audio_without_m4a):
        audio = audio_without_m4a
        edit_url = reverse("castaudio:edit", args=(audio.id,))
        r = authenticated_client.get(edit_url)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Delete" in content

    def test_get_edit_audio_without_m4a_no_filesize(self, settings, authenticated_client, audio_without_m4a):
        settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
        audio = audio_without_m4a

        # set the name to make bool(audio.m4a) True and save it (yes, this is needed)
        audio.m4a.name = "foobar"
        audio.save()

        edit_url = reverse("castaudio:edit", args=(audio.id,))
        r = authenticated_client.get(edit_url)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Delete" in content

    def test_post_edit_audio_invalid_form(self, authenticated_client, audio_urls, m4a_audio):
        m4a_audio.seek(m4a_audio.size)  # seek to end to make file empty/invalid
        post_data = {"m4a": m4a_audio}
        r = authenticated_client.post(audio_urls.edit, post_data)

        # make sure we don't get redirected to index
        assert r.status_code == 200

    def test_post_edit_audio_title(self, authenticated_client, audio_urls):
        audio = audio_urls.audio
        post_data = {
            "title": "changed title",
        }
        r = authenticated_client.post(audio_urls.edit, post_data)

        # make sure we get redirected to index
        assert r.status_code == 302
        assert r.url == audio_urls.index

        # make sure title was changes
        audio.refresh_from_db()
        assert audio.title == post_data["title"]

    def test_post_edit_audio_m4a(self, authenticated_client, audio_urls, m4a_audio):
        m4a_audio.seek(0)  # don't know why this is necessary :/
        post_data = {"m4a": m4a_audio}
        r = authenticated_client.post(audio_urls.edit, post_data)

        # make sure we get redirected to index
        assert r.status_code == 302
        assert r.url == audio_urls.index

        # teardown
        audio = Audio.objects.first()
        audio.m4a.delete()


class TestAudioDelete:
    pytestmark = pytest.mark.django_db

    def test_get_delete_audio(self, authenticated_client, audio_urls):
        r = authenticated_client.get(audio_urls.delete)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Are you sure you want to delete this audio?" in content

    def test_post_delete_audio(self, authenticated_client, audio_urls):
        audio = audio_urls.audio
        # post data is necessary because of if request.POST
        r = authenticated_client.post(audio_urls.delete, {"delete": "yes"})

        # make sure we get redirected to index
        assert r.status_code == 302
        assert r.url == audio_urls.index

        # make sure audio was deleted
        with pytest.raises(Audio.DoesNotExist):
            audio.refresh_from_db()


class TestAudioChosen:
    pytestmark = pytest.mark.django_db

    def test_get_chosen_audio_not_found(self, authenticated_client, audio_urls):
        audio = audio_urls.audio
        audio.delete()
        r = authenticated_client.get(audio_urls.chosen)

        assert r.status_code == 404

    def test_get_chosen_audio_success(self, authenticated_client, audio_urls):
        audio = audio_urls.audio
        r = authenticated_client.get(audio_urls.chosen)

        assert r.status_code == 200

        # make sure returned data belongs to the right audio instance
        data = r.json()
        assert data["result"]["title"] == audio.title


class TestAudioChooser:
    pytestmark = pytest.mark.django_db

    def test_get_audio_in_chooser(self, authenticated_client, audio_urls):
        audio = audio_urls.audio
        r = authenticated_client.get(audio_urls.chooser)

        assert r.status_code == 200

        # make sure existing audio is in chooser
        content = r.content.decode("utf-8")
        assert audio.title in content

        # make sure prefix for form fields is set
        assert "media-chooser-upload" in content

    def test_get_chooser_with_search(self, authenticated_client, audio_urls):
        r = authenticated_client.get(audio_urls.chooser, {"q": audio_urls.audio.title})

        assert r.status_code == 200

        # make sure searched audio is included in results
        assert r.context["audios"][0] == audio_urls.audio

    def test_get_chooser_with_search_invalid(self, authenticated_client, audio_urls):
        # {"p": "1"} (page 1) leads to the search form being invalid
        r = authenticated_client.get(audio_urls.chooser, {"p": "1"})

        assert r.status_code == 200

        # make sure searched audios is included in results
        assert r.context["audios"][0] == audio_urls.audio

    def test_get_chooser_with_pagination(self, authenticated_client, user):
        audio_models = []
        for i in range(1, 3):
            audio = Audio(user=user, title=f"audio {i}")
            audio.save()
            audio_models.append(audio)
        chooser_url = reverse("castaudio:chooser")
        with patch("cast.views.audio.CHOOSER_PAGINATION", return_value=1):
            r = authenticated_client.get(chooser_url, {"p": "1"})
        audios = r.context["audios"]

        # make sure we got last audio from first page
        assert len(audios) == 1
        assert audios[0] == audio_models[-1]

        with patch("cast.views.audio.CHOOSER_PAGINATION", return_value=1):
            r = authenticated_client.get(chooser_url, {"p": "2"})
        audios = r.context["audios"]

        # make sure we got first audio from last page
        assert len(audios) == 1
        assert audios[0] == audio_models[0]


class TestAudioChooserUpload:
    pytestmark = pytest.mark.django_db

    def test_get_audio_in_chooser_upload(self, authenticated_client, audio_urls):
        audio = audio_urls.audio
        r = authenticated_client.get(audio_urls.chooser_upload)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert audio.title in content

    def test_post_upload_audio_form_invalid(self, authenticated_client, m4a_audio):
        m4a_audio.seek(m4a_audio.size)  # seek to end to make file empty/invalid
        upload_url = reverse("castaudio:chooser_upload")
        post_data = {"media-chooser-upload-m4a": m4a_audio}
        r = authenticated_client.post(upload_url, post_data)

        assert r.status_code == 200
        assert r.context["message"] == "The audio could not be saved due to errors."

    def test_post_upload_audio(self, authenticated_client, m4a_audio, settings):
        settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
        upload_url = reverse("castaudio:chooser_upload")
        prefix = "media-chooser-upload"
        post_data = {
            f"{prefix}-title": "foobar",
            f"{prefix}-tags": "foo,bar,baz",
            f"{prefix}-m4a": m4a_audio,
        }
        r = authenticated_client.post(upload_url, post_data)

        assert r.status_code == 200

        # make sure field were saved correctly
        audio = Audio.objects.first()
        assert audio.title == post_data[f"{prefix}-title"]

        actual_tags = {t.name for t in audio.tags.all()}
        expected_tags = set(post_data[f"{prefix}-tags"].split(","))
        assert actual_tags == expected_tags

        # teardown
        audio.m4a.delete()
