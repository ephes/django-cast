"""Reusable database invalidation must reach each parallel worker."""

from pathlib import Path

import pytest

from tests.conftest import _reusable_test_db_path


@pytest.mark.parametrize("configured", ["test.sqlite3", "test.sqlite3_gw2"])
def test_worker_database_path(settings, monkeypatch, tmp_path, configured):
    settings.DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": tmp_path / configured}}
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw2")
    assert _reusable_test_db_path() == tmp_path / "test.sqlite3_gw2"


def test_serial_database_path(settings, monkeypatch):
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    settings.DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": "test.sqlite3"}}
    assert _reusable_test_db_path() == Path("test.sqlite3")
