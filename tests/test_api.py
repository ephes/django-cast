from datetime import timedelta

from django.urls import reverse

import pytest

from .factories import UserFactory


# from cast.access_log import pandas_rows_to_dict
# from cast.access_log import get_last_request_position
# from cast.access_log import get_dataframe_from_position


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


class TestPodcastAudio:
    @pytest.mark.django_db
    def test_podlove_detail_endpoint_without_authentication(self, api_client, audio):
        """Should be accessible without authentication."""
        podlove_detail_url = reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk})
        r = api_client.get(podlove_detail_url, format="json")
        assert r.status_code == 200

    @pytest.mark.django_db
    def test_podlove_detail_endpoint_duration(self, api_client, audio):
        """Test whether microseconds get stripped away from duration via api - they have
        to be for podlove player to work.
        """
        delta = timedelta(days=0, hours=1, minutes=10, seconds=20, microseconds=40)
        audio.duration = delta
        audio.save()
        assert "." in str(audio.duration)
        podlove_detail_url = reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk})
        r = api_client.get(podlove_detail_url, format="json")
        assert "." not in r.json()["duration"]

    @pytest.mark.django_db
    def test_podlove_detail_endpoint_chaptermarks(self, api_client, audio, chaptermarks):
        """Test whether chaptermarks get delivered via podlove endpoint."""
        print("chaptermarks: ", chaptermarks)
        podlove_detail_url = reverse("cast:api:audio_podlove_detail", kwargs={"pk": audio.pk})
        r = api_client.get(podlove_detail_url, format="json")
        chapters = r.json()["chapters"]
        for chapter in chapters:
            # assert microseconds are stripped away
            assert "." not in chapter["start"]
            assert ":" in chapter["start"]
        assert len(chapters) == 3
        # assert reordering
        assert chapters[-1]["title"] == "coughing"


class TestRequest:
    @classmethod
    def setup_class(cls):
        cls.list_url = reverse("cast:api:request_list")

    @pytest.mark.django_db
    def test_request_list_endpoint_without_authentication(self, api_client):
        """Should not be accessible without authentication."""
        r = api_client.get(self.list_url, format="json")
        assert r.status_code == 403

    @pytest.mark.django_db
    def test_request_list_endpoint_with_authentication(self, api_client):
        """Check for list result when accessing the list endpoint
        being logged in.
        """
        user = UserFactory()
        api_client.login(username=user.username, password="password")
        r = api_client.get(self.list_url, format="json")
        # dont redirect to login page
        assert r.status_code == 200
        assert "results" in r.json()


#    @pytest.mark.django_db
#    def test_request_list_endpoint_non_bulk_insert(self, api_client, access_log_path):
#        user = UserFactory()
#        api_client.login(username=user.username, password="password")
#        df = get_dataframe_from_position(access_log_path, start_position=0)
#        raw_rows = df.fillna("").to_dict(orient="rows")
#        rows = pandas_rows_to_dict(raw_rows)
#        row = rows[0]
#        r = api_client.post(self.list_url, data=row, format="json")
#        assert r.status_code == 201

#    @pytest.mark.django_db
#    def test_request_list_endpoint_bulk_insert(self, api_client, access_log_path):
#        user = UserFactory()
#        api_client.login(username=user.username, password="password")
#        df = get_dataframe_from_position(access_log_path, start_position=0)
#        raw_rows = df.fillna("").to_dict(orient="rows")
#        rows = pandas_rows_to_dict(raw_rows)
#        r = api_client.post(self.list_url, data=rows, format="json")
#        assert r.status_code == 201
#        assert Request.objects.count() == df.shape[0]

#    @pytest.mark.django_db
#    def test_request_list_endpoint_incremental_insert(
#        self, api_client, access_log_path
#    ):
#        user = UserFactory()
#        api_client.login(username=user.username, password="password")
#        Request.objects.all().delete()
#
#        # insert just first row
#        df = get_dataframe_from_position(access_log_path, start_position=0)
#        raw_rows = df.fillna("").to_dict(orient="rows")
#        rows = pandas_rows_to_dict(raw_rows)
#        row = rows[0]
#        r = api_client.post(self.list_url, data=row, format="json")
#        assert r.status_code == 201
#
#        # get last position (should be 4 because first 5 are the same)
#        last_request = Request.objects.all().order_by("-timestamp")[0]
#        last_position = get_last_request_position(access_log_path, last_request)
#        assert last_position == 4
#
#        # insert starting at position 4
#        df = get_dataframe_from_position(access_log_path, start_position=last_position)
#        raw_rows = df.fillna("").to_dict(orient="rows")
#        rows = pandas_rows_to_dict(raw_rows)
#        r = api_client.post(self.list_url, data=rows, format="json")
#        assert r.status_code == 201
#
#        # assert number of unique lines in access.log and objects in database are equal
#        # we omitted some lines intentionally
#        number_of_unique_lines = 0
#        with open(access_log_path) as f:
#            number_of_unique_lines = len(set([l for l in f]))
#        assert Request.objects.count() == number_of_unique_lines
