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

        # make sure video title included in rendered video block
        assert video.title in content


def get_endpoint_urls_without_args():
    urls = {}
    view_names = ["index", "add", "chooser", "chooser_upload"]
    for view_name in view_names:
        video_view_name = f"video_{view_name}"
        urls[video_view_name] = reverse(f"castmedia:{video_view_name}")
    return urls


def get_endpoint_urls_with_args(video):
    urls = {}
    view_names = ["edit", "delete", "chosen"]
    for view_name in view_names:
        video_view_name = f"video_{view_name}"
        urls[video_view_name] = reverse(f"castmedia:{video_view_name}", args=(video.id,))
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

    def test_get_video_index(self, authenticated_client, video_urls):
        r = authenticated_client.get(video_urls.video_index)

        assert r.status_code == 200
        content = r.content.decode("utf-8")

        # make sure it's the media results page
        assert "html" in content
        assert "media-results" in content

        # make sure video_urls.video is included in results
        assert video_urls.video.title in content

    def test_get_video_index_ajax(self, authenticated_client, video_urls):
        headers = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
        r = authenticated_client.get(video_urls.video_index, **headers)

        assert r.status_code == 200
        content = r.content.decode("utf-8")

        # make sure it's the media results page
        assert "table" in content
        assert "listing" in content

        # make sure video_urls.video is included in results
        assert video_urls.video.title in content


class TestVideoAdd:
    pytestmark = pytest.mark.django_db

    def test_get_add_video(self, authenticated_client, video_urls):
        r = authenticated_client.get(video_urls.video_add)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Uploading…" in content

    def test_post_add_video_invalid_form(self, authenticated_client):
        add_url = reverse(f"castmedia:video_add")

        post_data = {
            "title": "foobar",
            "tags": "foo,bar,baz",
        }
        r = authenticated_client.post(add_url, post_data)

        # make sure we dont get redirected to video_index
        assert r.status_code == 200

        # make sure we didn't create a video
        Video.objects.first() is None

    def test_post_add_video(self, authenticated_client, minimal_mp4):
        add_url = reverse(f"castmedia:video_add")

        post_data = {
            "title": "foobar",
            "tags": "foo,bar,baz",
            "original": minimal_mp4,
        }
        r = authenticated_client.post(add_url, post_data)

        # make sure we get redirected to video_index
        assert r.status_code == 302
        assert r.url == reverse(f"castmedia:video_index")

        # make sure field were saved correctly
        video = Video.objects.first()
        assert video.title == post_data["title"]

        actual_tags = set([t.name for t in video.tags.all()])
        expected_tags = set(post_data["tags"].split(","))
        assert actual_tags == expected_tags

    def test_post_add_video(self, authenticated_client, minimal_mp4):
        add_url = reverse(f"castmedia:video_add")

        post_data = {
            "title": "foobar",
            "tags": "foo,bar,baz",
            "original": minimal_mp4,
        }
        r = authenticated_client.post(add_url, post_data)

        # make sure we get redirected to video_index
        assert r.status_code == 302
        assert r.url == reverse(f"castmedia:video_index")

        # make sure field were saved correctly
        video = Video.objects.first()
        assert video.title == post_data["title"]

        actual_tags = set([t.name for t in video.tags.all()])
        expected_tags = set(post_data["tags"].split(","))
        assert actual_tags == expected_tags


class TestVideoEdit:
    pytestmark = pytest.mark.django_db

    def test_get_edit_video(self, authenticated_client, video_urls):
        r = authenticated_client.get(video_urls.video_edit)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Delete" in content

    def test_post_edit_video_invalid_form(self, authenticated_client, video_urls):
        post_data = {"foo": "bar"}  # must not be empty because of if request.POST claus
        r = authenticated_client.post(video_urls.video_edit, post_data)

        # make sure we dont get redirected to video_index
        assert r.status_code == 200

    def test_post_edit_video(self, authenticated_client, video_urls):
        video = video_urls.video
        post_data = {
            "title": "changed title",
        }
        r = authenticated_client.post(video_urls.video_edit, post_data)

        # make sure we get redirected to video_index
        assert r.status_code == 302
        assert r.url == video_urls.video_index

        # make sure title was changes
        video.refresh_from_db()
        assert video.title == post_data["title"]


class TestVideoDelete:
    pytestmark = pytest.mark.django_db

    def test_get_delete_video(self, authenticated_client, video_urls):
        r = authenticated_client.get(video_urls.video_delete)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Are you sure you want to delete this video?" in content

    def test_post_delete_video(self, authenticated_client, video_urls):
        video = video_urls.video
        # post data is necessary because of if request.POST
        r = authenticated_client.post(video_urls.video_delete, {"delete": "yes"})

        # make sure we get redirected to video_index
        assert r.status_code == 302
        assert r.url == video_urls.video_index

        # make sure video was deleted
        with pytest.raises(Video.DoesNotExist):
            video.refresh_from_db()


class TestVideoChosen:
    pytestmark = pytest.mark.django_db

    def test_get_chosen_video_not_found(self, authenticated_client, video_urls):
        video = video_urls.video
        video.delete()
        r = authenticated_client.get(video_urls.video_chosen)

        assert r.status_code == 404

    def test_get_chosen_video_success(self, authenticated_client, video_urls):
        video = video_urls.video
        r = authenticated_client.get(video_urls.video_chosen)

        assert r.status_code == 200

        # make sure returned data belongs to the right video instance
        data = r.json()
        assert data["result"]["title"] == video.title


class TestVideoChooser:
    pytestmark = pytest.mark.django_db

    def test_get_video_in_chooser(self, authenticated_client, video_urls):
        video = video_urls.video
        r = authenticated_client.get(video_urls.video_chooser)

        assert r.status_code == 200

        # make sure existing video is in chooser
        content = r.content.decode("utf-8")
        assert video.title in content

        # make sure prefix for form fields is set
        assert "media-chooser-upload" in content


class TestVideoChooserUpload:
    pytestmark = pytest.mark.django_db

    def test_get_video_in_chooser_upload(self, authenticated_client, video_urls):
        video = video_urls.video
        r = authenticated_client.get(video_urls.video_chooser_upload)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert video.title in content

    def test_post_upload_video(self, authenticated_client, minimal_mp4):
        upload_url = reverse(f"castmedia:video_chooser_upload")
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

        actual_tags = set([t.name for t in video.tags.all()])
        expected_tags = set(post_data[f"{prefix}-tags"].split(","))
        assert actual_tags == expected_tags
