import pytest
from django.urls import reverse


class TestVideoUpload:
    @pytest.mark.django_db
    def test_upload_video_not_authenticated(self, client, minimal_mp4):
        upload_url = reverse("cast:api:upload_video")

        minimal_mp4.seek(0)
        r = client.post(upload_url, {"original": minimal_mp4})
        # redirect to login
        assert r.status_code == 302

    @pytest.mark.django_db
    def test_upload_video_authenticated(self, client, user, minimal_mp4):
        # login
        r = client.login(username=user.username, password=user._password)

        self.called_create_poster = False

        def set_called_create_poster():
            self.called_create_poster = True

        # mock create poster?
        # Video._saved_create_poster = Video._create_poster
        # Video._create_poster = lambda x: set_called_create_poster()

        # upload
        upload_url = reverse("cast:api:upload_video")
        minimal_mp4.seek(0)
        r = client.post(upload_url, {"original": minimal_mp4})

        # unmock
        # Video._create_poster = Video._saved_create_poster

        assert r.status_code == 201
        assert int(r.content.decode("utf-8")) > 0

        # check mocked function has been called - no longer necessary since we use
        # a real mp4 now.
        # assert self.called_create_poster
