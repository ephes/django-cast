import pytest

from django.urls import reverse

class TestVideoIndex:
    pytestmark = pytest.mark.django_db

    def test_get_video_index_not_authenticated(self, client):
        index_url = reverse("castmedia:video_index")

        r = client.get(index_url)

        # redirect to login
        assert r.status_code == 302
        login_url = reverse("wagtailadmin_login")
        assert login_url in r.url
    
    def test_get_video_index_not_authenticated(self, client, user):
        index_url = reverse("castmedia:video_index")

        _ = client.login(username=user.username, password=user._password)
        r = client.get(index_url, follow=True)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "html" in content
        assert "media-results" in content
