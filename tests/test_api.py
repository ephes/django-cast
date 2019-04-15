import pytest

from django.urls import reverse

from .factories import UserFactory


class TestBlogImage:
    @classmethod
    def setup_class(cls):
        cls.list_url = reverse("cast:api:image_list")
        cls.detail_url = reverse("cast:api:image_detail", kwargs={"pk": 1})

    @pytest.mark.django_db
    def test_image_list_endpoint_without_authentication(self, api_client):
        """Check for not authenticated status code if trying to access the list
        endpoint without being authenticated.
        """
        r = api_client.get(self.list_url, format="json")
        assert r.status_code == 403

    @pytest.mark.django_db
    def test_image_detail_endpoint_without_authentication(self, api_client):
        """Check for not authenticated status code if trying to access the
        detail endpoint without being authenticated.
        """
        r = api_client.get(self.detail_url, format="json")
        assert r.status_code == 403

    @pytest.mark.django_db
    def test_image_list_endpoint_with_authentication(self, api_client):
        """Check for list result when accessing the list endpoint
        being logged in.
        """
        user = UserFactory()
        api_client.login(username=user.username, password="password")
        r = api_client.get(self.list_url, format="json")
        # dont redirect to login page
        assert r.status_code == 200
        assert "results" in r.json()


class TestBlogGallery:
    @classmethod
    def setup_class(cls):
        cls.list_url = reverse("cast:api:gallery_list")
        cls.detail_url = reverse("cast:api:gallery_detail", kwargs={"pk": 1})

    @pytest.mark.django_db
    def test_gallery_list_endpoint_without_authentication(self, api_client):
        """Check for not authenticated status code if trying to access the list
        endpoint without being authenticated.
        """
        r = api_client.get(self.list_url, format="json")
        assert r.status_code == 403

    @pytest.mark.django_db
    def test_gallery_detail_endpoint_without_authentication(self, api_client):
        """Check for not authenticated status code if trying to access the
        detail endpoint without being authenticated.
        """
        r = api_client.get(self.detail_url, format="json")
        assert r.status_code == 403

    @pytest.mark.django_db
    def test_gallery_list_endpoint_with_authentication(self, api_client):
        """Check for list result when accessing the list endpoint
        being logged in.
        """
        user = UserFactory()
        api_client.login(username=user.username, password="password")
        r = api_client.get(self.list_url, format="json")
        # dont redirect to login page
        assert r.status_code == 200
        assert "results" in r.json()


class TestBlogVideo:
    @classmethod
    def setup_class(cls):
        cls.list_url = reverse("cast:api:video_list")
        cls.detail_url = reverse("cast:api:video_detail", kwargs={"pk": 1})

    @pytest.mark.django_db
    def test_video_list_endpoint_without_authentication(self, api_client):
        """Check for not authenticated status code if trying to access the list
        endpoint without being authenticated.
        """
        r = api_client.get(self.list_url, format="json")
        assert r.status_code == 403

    @pytest.mark.django_db
    def test_video_detail_endpoint_without_authentication(self, api_client):
        """Check for not authenticated status code if trying to access the
        detail endpoint without being authenticated.
        """
        r = api_client.get(self.detail_url, format="json")
        assert r.status_code == 403

    @pytest.mark.django_db
    def test_video_list_endpoint_with_authentication(self, api_client):
        """Check for list result when accessing the list endpoint
        being logged in.
        """
        user = UserFactory()
        api_client.login(username=user.username, password="password")
        r = api_client.get(self.list_url, format="json")
        # dont redirect to login page
        assert r.status_code == 200
        assert "results" in r.json()


class TestBlogAudio:
    @classmethod
    def setup_class(cls):
        cls.list_url = reverse("cast:api:audio_list")
        cls.detail_url = reverse("cast:api:audio_detail", kwargs={"pk": 1})

    @pytest.mark.django_db
    def test_audio_list_endpoint_without_authentication(self, api_client):
        """Check for not authenticated status code if trying to access the list
        endpoint without being authenticated.
        """
        r = api_client.get(self.list_url, format="json")
        assert r.status_code == 403

    @pytest.mark.django_db
    def test_audio_detail_endpoint_without_authentication(self, api_client):
        """Check for not authenticated status code if trying to access the
        detail endpoint without being authenticated.
        """
        r = api_client.get(self.detail_url, format="json")
        assert r.status_code == 403

    @pytest.mark.django_db
    def test_audio_list_endpoint_with_authentication(self, api_client):
        """Check for list result when accessing the list endpoint
        being logged in.
        """
        user = UserFactory()
        api_client.login(username=user.username, password="password")
        r = api_client.get(self.list_url, format="json")
        # dont redirect to login page
        assert r.status_code == 200
        assert "results" in r.json()

    @pytest.mark.django_db
    def test_podlove_detail_endpoint_without_authentication(self, api_client, audio):
        """Should be accessible without authentication."""
        podlove_detail_url = reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk})
        r = api_client.get(podlove_detail_url, format="json")
        assert r.status_code == 200
