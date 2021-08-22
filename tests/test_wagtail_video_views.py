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
        assert False
    
    def test_get_video_index(self, client, user):
        _ = client.login(username=user.username, password=user._password)
        r = client.get(self.index_url, follow=True)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "html" in content
        assert "media-results" in content


    # test for video in list of videos

