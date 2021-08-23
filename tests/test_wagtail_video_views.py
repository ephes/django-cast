import pytest

from django.urls import reverse


class TestVideoIndexNotAuthenticated:
    index_url = reverse("castmedia:video_index")

    def test_get_video_index_not_authenticated(self, client):
        r = client.get(self.index_url)

        # redirect to login
        assert r.status_code == 302
        login_url = reverse("wagtailadmin_login")
        assert login_url in r.url


class TestVideoIndex:
    pytestmark = pytest.mark.django_db
    index_url = reverse("castmedia:video_index")

    def test_get_video_index(self, authenticated_client):
        r = authenticated_client.get(self.index_url, follow=True)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "html" in content
        assert "media-results" in content

    # test for video in list of videos


class TestVideoAdd:
    pytestmark = pytest.mark.django_db
    add_url = reverse("castmedia:video_add")

    @pytest.fixture(autouse=True)
    def setup_root_page(self, root_page):
        # without this, there's no wagtail root page
        self.root_page = root_page

    def test_get_add_video(self, authenticated_client):
        r = authenticated_client.get(self.add_url)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Uploading…" in content

    def test_post_add_video(self, authenticated_client):
        r = authenticated_client.post(self.add_url)
        assert False
