from unittest.mock import patch

import pytest
from django.urls import reverse

from cast.models import Video


class TestPostWithVideoDetail:
    pytestmark = pytest.mark.django_db

    def test_get_post_with_video_detail(self, client, post_with_video):
        video = post_with_video.videos.first()
        detail_url = post_with_video.get_url()

        r = client.get(detail_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "html" in content

        # make sure video is included in rendered video block
        assert "block-video" in content
        assert video.filename in content


def get_endpoint_urls_without_args():
    urls = {}
    view_names = ["index", "add", "chooser", "chooser_upload"]
    for view_name in view_names:
        urls[view_name] = reverse(f"castvideo:{view_name}")
    return urls


def get_endpoint_urls_with_args(video):
    urls = {}
    view_names = ["edit", "delete", "chosen"]
    for view_name in view_names:
        urls[view_name] = reverse(f"castvideo:{view_name}", args=(video.id,))
    return urls


class VideoUrls:
    def __init__(self, video):
        self.video = video
        self.urls = get_endpoint_urls_without_args()
        self.urls.update(get_endpoint_urls_with_args(video))

    def __getattr__(self, item):
        return self.urls[item]


@pytest.fixture
def video_urls(video):
    return VideoUrls(video)


class TestAllVideoEndpoints:
    pytestmark = pytest.mark.django_db

    def test_get_all_not_authenticated(self, client, video_urls):
        for view_name, url in video_urls.urls.items():
            r = client.get(url)

            # redirect to login
            assert r.status_code == 302
            login_url = reverse("wagtailadmin_login")
            assert login_url in r.url

    def test_get_all_authenticated(self, authenticated_client, video_urls):
        for view_name, url in video_urls.urls.items():
            r = authenticated_client.get(url)

            # assert we are not redirected to login
            assert r.status_code == 200


class TestVideoIndex:
    pytestmark = pytest.mark.django_db

    def test_get_index(self, authenticated_client, video_urls):
        r = authenticated_client.get(video_urls.index)

        assert r.status_code == 200
        content = r.content.decode("utf-8")

        # make sure it's the media results page
        assert "html" in content
        assert "media-results" in content

        # make sure video_urls.video is included in results
        assert video_urls.video.title in content

    def test_get_index_ajax(self, authenticated_client, video_urls):
        headers = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
        r = authenticated_client.get(video_urls.index, **headers)

        assert r.status_code == 200
        content = r.content.decode("utf-8")

        # make sure it's the media results page
        assert "table" in content
        assert "listing" in content

        # make sure video_urls.video is included in results
        assert video_urls.video.title in content

    def test_get_index_with_search(self, authenticated_client, video_urls):
        r = authenticated_client.get(video_urls.index, {"q": video_urls.video.title})

        assert r.status_code == 200
        content = r.content.decode("utf-8")

        # make sure it's the media results page
        assert "html" in content
        assert "media-results" in content

        # make sure video_urls.video is included in results
        assert video_urls.video.title in content

    def test_get_index_with_search_invalid(self, authenticated_client, video_urls):
        r = authenticated_client.get(video_urls.index, {"q": " "})

        assert r.status_code == 200
        content = r.content.decode("utf-8")

        # make sure it's the media results page
        assert "html" in content
        assert "media-results" in content

        # make sure video_urls.video is included in results
        print(content)
        assert video_urls.video.title in content

    def test_get_index_with_pagination(self, authenticated_client, user):
        video_models = []
        for i in range(1, 3):
            video = Video(user=user, title=f"video {i}")
            video.save()
            video_models.append(video)
        index_url = reverse("castvideo:index")
        with patch("cast.views.video.MENU_ITEM_PAGINATION", return_value=1):
            r = authenticated_client.get(index_url, {"p": "1"})
        videos = r.context["videos"]

        # make sure we got last video from first page
        assert len(videos) == 1
        assert videos[0] == video_models[-1]

        with patch("cast.views.video.MENU_ITEM_PAGINATION", return_value=1):
            r = authenticated_client.get(index_url, {"p": "2"})
        videos = r.context["videos"]

        # make sure we got first video from last page
        assert len(videos) == 1
        assert videos[0] == video_models[0]


class TestVideoAdd:
    pytestmark = pytest.mark.django_db

    def test_get_add_video(self, authenticated_client, video_urls):
        r = authenticated_client.get(video_urls.add)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Uploading…" in content

    def test_post_add_video_invalid_form(self, authenticated_client):
        add_url = reverse("castvideo:add")

        post_data = {
            "title": "foobar",
            "tags": "foo,bar,baz",
        }
        r = authenticated_client.post(add_url, post_data)

        # make sure we dont get redirected to index
        assert r.status_code == 200

        # make sure we didn't create a video
        Video.objects.first() is None

    def test_post_add_video(self, authenticated_client, minimal_mp4):
        add_url = reverse("castvideo:add")

        post_data = {
            "title": "foobar",
            "tags": "foo,bar,baz",
            "original": minimal_mp4,
        }
        r = authenticated_client.post(add_url, post_data)

        # make sure we get redirected to index
        assert r.status_code == 302
        assert r.url == reverse("castvideo:index")

        # make sure field were saved correctly
        video = Video.objects.first()
        assert video.title == post_data["title"]

        actual_tags = {t.name for t in video.tags.all()}
        expected_tags = set(post_data["tags"].split(","))
        assert actual_tags == expected_tags


class TestVideoEdit:
    pytestmark = pytest.mark.django_db

    def test_get_edit_video(self, authenticated_client, video_urls):
        r = authenticated_client.get(video_urls.edit)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Delete" in content

    def test_get_edit_video_without_original(self, authenticated_client, video_without_original):
        video = video_without_original
        edit_url = reverse("castvideo:edit", args=(video.id,))
        r = authenticated_client.get(edit_url)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Delete" in content

    def test_get_edit_video_with_original_no_filesize(self, settings, authenticated_client, video_without_file):
        settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
        video = video_without_file
        edit_url = reverse("castvideo:edit", args=(video.id,))
        r = authenticated_client.get(edit_url)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Delete" in content

    def test_post_edit_video_invalid_form(self, authenticated_client, video_urls):
        post_data = {"foo": "bar"}  # must not be empty because of if request.POST claus
        r = authenticated_client.post(video_urls.edit, post_data)

        # make sure we dont get redirected to index
        assert r.status_code == 200

    def test_post_edit_video_title(self, authenticated_client, video_urls):
        video = video_urls.video
        post_data = {
            "title": "changed title",
        }
        r = authenticated_client.post(video_urls.edit, post_data)

        # make sure we get redirected to index
        assert r.status_code == 302
        assert r.url == video_urls.index

        # make sure title was changes
        video.refresh_from_db()
        assert video.title == post_data["title"]

    def test_post_edit_video_original(self, authenticated_client, video_urls, minimal_mp4):
        post_data = {
            "title": "asdf",
            "original": minimal_mp4,
        }
        r = authenticated_client.post(video_urls.edit, post_data)

        # make sure we get redirected to index
        assert r.status_code == 302
        assert r.url == video_urls.index


class TestVideoDelete:
    pytestmark = pytest.mark.django_db

    def test_get_delete_video(self, authenticated_client, video_urls):
        r = authenticated_client.get(video_urls.delete)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Are you sure you want to delete this video?" in content

    def test_post_delete_video(self, authenticated_client, video_urls):
        video = video_urls.video
        # post data is necessary because of if request.POST
        r = authenticated_client.post(video_urls.delete, {"delete": "yes"})

        # make sure we get redirected to index
        assert r.status_code == 302
        assert r.url == video_urls.index

        # make sure video was deleted
        with pytest.raises(Video.DoesNotExist):
            video.refresh_from_db()


class TestVideoChosen:
    pytestmark = pytest.mark.django_db

    def test_get_chosen_video_not_found(self, authenticated_client, video_urls):
        video = video_urls.video
        video.delete()
        r = authenticated_client.get(video_urls.chosen)

        assert r.status_code == 404

    def test_get_chosen_video_success(self, authenticated_client, video_urls):
        video = video_urls.video
        r = authenticated_client.get(video_urls.chosen)

        assert r.status_code == 200

        # make sure returned data belongs to the right video instance
        data = r.json()
        assert data["result"]["title"] == video.title


class TestVideoChooser:
    pytestmark = pytest.mark.django_db

    def test_get_video_in_chooser(self, authenticated_client, video_urls):
        video = video_urls.video
        r = authenticated_client.get(video_urls.chooser)

        assert r.status_code == 200

        # make sure existing video is in chooser
        content = r.content.decode("utf-8")
        assert video.title in content

        # make sure prefix for form fields is set
        assert "media-chooser-upload" in content

    def test_get_video_chooser_with_search(self, authenticated_client, video_urls):
        r = authenticated_client.get(video_urls.chooser, {"q": video_urls.video.title})

        assert r.status_code == 200

        # make sure searched video is included in results
        assert r.context["videos"][0] == video_urls.video

    def test_get_video_chooser_with_search_invalid(self, authenticated_client, video_urls):
        # {"p": "1"} (page 1) leads to the search form being invalid
        r = authenticated_client.get(video_urls.chooser, {"p": "1"})

        assert r.status_code == 200

        # make sure searched video is included in results
        assert r.context["videos"][0] == video_urls.video

    def test_get_video_chooser_with_pagination(self, authenticated_client, user):
        video_models = []
        for i in range(1, 3):
            video = Video(user=user, title=f"video {i}")
            video.save()
            video_models.append(video)
        chooser_url = reverse("castvideo:chooser")
        with patch("cast.views.video.CHOOSER_PAGINATION", return_value=1):
            r = authenticated_client.get(chooser_url, {"p": "1"})
        videos = r.context["videos"]

        # make sure we got last video from first page
        assert len(videos) == 1
        assert videos[0] == video_models[-1]

        with patch("cast.views.video.CHOOSER_PAGINATION", return_value=1):
            r = authenticated_client.get(chooser_url, {"p": "2"})
        videos = r.context["videos"]

        # make sure we got first video from last page
        assert len(videos) == 1
        assert videos[0] == video_models[0]


class TestVideoChooserUpload:
    pytestmark = pytest.mark.django_db

    def test_get_video_in_chooser_upload(self, authenticated_client, video_urls):
        video = video_urls.video
        r = authenticated_client.get(video_urls.chooser_upload)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert video.title in content

    def test_post_upload_video_form_invalid(self, authenticated_client):
        upload_url = reverse("castvideo:chooser_upload")
        post_data = {"foo": "bar"}
        r = authenticated_client.post(upload_url, post_data)

        assert r.status_code == 200

        # make sure error is reported
        messages = list(r.context["messages"])
        assert len(messages) == 1
        assert str(messages[0]).rstrip() == "The video could not be saved due to errors."

    def test_post_upload_video(self, authenticated_client, minimal_mp4):
        upload_url = reverse("castvideo:chooser_upload")
        prefix = "media-chooser-upload"
        post_data = {
            f"{prefix}-title": "foobar",
            f"{prefix}-tags": "foo,bar,baz",
            f"{prefix}-original": minimal_mp4,
        }
        r = authenticated_client.post(upload_url, post_data)

        assert r.status_code == 200

        # make sure field were saved correctly
        video = Video.objects.first()
        assert video.title == post_data[f"{prefix}-title"]

        actual_tags = {t.name for t in video.tags.all()}
        expected_tags = set(post_data[f"{prefix}-tags"].split(","))
        assert actual_tags == expected_tags
