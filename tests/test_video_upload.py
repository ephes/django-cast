import pytest

from django.urls import reverse

from cast.models import Video


class TestVideoUpload:
    @pytest.mark.django_db
    def test_upload_video_not_authenticated(self, client, image_1px_io):
        upload_url = reverse("cast:api:upload_video")

        image_1px_io.seek(0)
        r = client.post(upload_url, {"original": image_1px_io})
        # redirect to login
        assert r.status_code == 302

    @pytest.mark.django_db
    def test_upload_video_authenticated(self, client, user, image_1px_io):
        # login
        r = client.login(username=user.username, password=user._password)

        self.called_create_poster = False

        def set_called_create_poster():
            self.called_create_poster = True

        Video._saved_create_poster = Video._create_poster
        Video._create_poster = lambda x: set_called_create_poster()

        # upload
        upload_url = reverse("cast:api:upload_video")
        image_1px_io.seek(0)
        r = client.post(upload_url, {"original": image_1px_io})

        Video._create_poster = Video._saved_create_poster

        assert r.status_code == 201
        assert self.called_create_poster
        assert int(r.content.decode("utf-8")) > 0
