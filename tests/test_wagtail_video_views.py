import pytest

from django.urls import reverse

from cast.models import Video


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


class TestVideoAdd:
    pytestmark = pytest.mark.django_db

    def test_get_add_video(self, authenticated_client, video_urls):
        r = authenticated_client.get(video_urls.video_add)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Uploading…" in content

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