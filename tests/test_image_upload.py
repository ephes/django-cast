from django.urls import reverse

import pytest


class TestImageUpload:
    @pytest.mark.django_db
    def test_upload_image_not_authenticated(self, client, small_jpeg_io):
        upload_url = reverse("cast:api:upload_image")

        small_jpeg_io.seek(0)
        r = client.post(upload_url, {"original": small_jpeg_io})
        # redirect to login
        assert r.status_code == 302

    @pytest.mark.django_db
    def test_upload_image_authenticated(self, client, user, small_jpeg_io):
        # login
        r = client.login(username=user.username, password=user._password)

        # upload
        upload_url = reverse("cast:api:upload_image")
        small_jpeg_io.seek(0)
        r = client.post(upload_url, {"original": small_jpeg_io})

        assert r.status_code == 201
        assert int(r.content.decode("utf-8")) > 0
