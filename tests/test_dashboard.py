from django.urls import reverse

import pytest

from .factories import UserFactory


class TestDashboard:
    pytestmark = pytest.mark.django_db

    @classmethod
    def setup_class(cls):
        cls.dashboard_url = reverse("cast:dashboard")

    def test_get_dashboard_without_authentication(self, client):
        r = client.get(self.dashboard_url)
        # redirect to login page
        assert r.status_code == 302

    def test_get_dashboard_with_authentication(self, client):
        user = UserFactory()
        client.login(username=user.username, password="password")
        r = client.get(self.dashboard_url)
        # dont redirect to login page
        assert r.status_code == 200
        assert "Dashboard" in r.content.decode("utf8")
