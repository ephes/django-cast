import pytest

from django.urls import reverse


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
    index_url = reverse("castmedia:video_index")

    def test_get_video_index(self, authenticated_client, video_urls):
        r = authenticated_client.get(video_urls.video_index, follow=True)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "html" in content
        assert "media-results" in content

    # test for video in list of videos


class TestVideoAdd:
    pytestmark = pytest.mark.django_db
    add_url = reverse("castmedia:video_add")

    def test_get_add_video(self, authenticated_client, video_urls):
        r = authenticated_client.get(video_urls.video_add)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Uploading…" in content

    # def test_post_add_video(self, authenticated_client):
    #     r = authenticated_client.post(self.add_url)
    #     assert False
