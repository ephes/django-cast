import pytest

from django.urls import reverse


class TestVideoIndex:
    pytestmark = pytest.mark.django_db
    index_url = reverse("castmedia:video_index")

    def test_get_video_index_not_authenticated(self, client):
        r = client.get(self.index_url)

        # redirect to login
        assert r.status_code == 302
        login_url = reverse("wagtailadmin_login")
        assert login_url in r.url
    
    def test_get_video_index(self, client, user):
        _ = client.login(username=user.username, password=user._password)
        r = client.get(self.index_url, follow=True)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "html" in content
        assert "media-results" in content


    # test for video in list of videos


class TestVideoAddAuthenticated:
    pytestmark = pytest.mark.django_db
    add_url = reverse("castmedia:video_add")

    @pytest.fixture(autouse=True)
    def login(self, client, user):
        _ = client.login(username=user.username, password=user._password)
        self.client = client
        self.user = user

    @pytest.fixture(autouse=True)
    def setup_root_page(self, root_page):
        # without this, there's no wagtail root page
        self.root_page = root_page

    def test_get_add_video(self):
        r = self.client.get(self.add_url)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Uploading…" in content
