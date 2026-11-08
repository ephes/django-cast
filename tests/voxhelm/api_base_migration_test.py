"""The Voxhelm API base moved from a site setting to deployment configuration."""

import importlib
import logging
from types import SimpleNamespace

import pytest

from cast.checks import check_cast_voxhelm_api_base

migration = importlib.import_module("cast.migrations.0088_remove_voxhelmsettings_api_base")


class Rows:
    def __init__(self, rows):
        self.rows = rows
        self.alias = None

    def using(self, alias):
        self.alias = alias
        return self

    def exclude(self, **kwargs):
        assert kwargs == {"api_base": ""}
        return self

    def values(self, *fields):
        assert fields == ("site_id", "api_base", "api_token")
        return [row for row in self.rows if row["api_base"]]


def run(rows):
    objects = Rows(rows)
    model = SimpleNamespace(objects=objects)
    fake_apps = SimpleNamespace(get_model=lambda app, name: model)
    migration.warn_about_stored_api_bases(fake_apps, SimpleNamespace(connection=SimpleNamespace(alias="default")))
    assert objects.alias == "default"


@pytest.fixture
def no_deployment_base(settings, monkeypatch):
    settings.CAST_VOXHELM_API_BASE = ""
    settings.CAST_VOXHELM_API_KEY = ""
    monkeypatch.delenv("CAST_VOXHELM_API_BASE", raising=False)
    monkeypatch.delenv("CAST_VOXHELM_API_KEY", raising=False)


def test_migration_warns_when_stored_base_differs(settings, caplog):
    settings.CAST_VOXHELM_API_BASE = "https://voxhelm.example"
    settings.CAST_VOXHELM_API_KEY = ""
    rows = [
        {"site_id": 1, "api_base": "https://user:secret@internal.example:8443/admin?x=1#/v1", "api_token": "t"},
        {"site_id": 2, "api_base": " https://voxhelm.example/v1/ ", "api_token": ""},
        {"site_id": 3, "api_base": "", "api_token": ""},
        {"site_id": 4, "api_base": "   ", "api_token": ""},
    ]
    with caplog.at_level(logging.WARNING, logger="cast.migrations"):
        run(rows)
    [record] = caplog.records
    message = record.getMessage()
    assert "site 1" in message
    assert "https://internal.example:8443/admin" in message
    assert "secret" not in message and "x=1" not in message
    assert "deployment CAST_VOXHELM_API_BASE (https://voxhelm.example)" in message
    assert "A site API token is still stored" in message


def test_migration_warns_that_generation_stays_disabled_without_deployment_base(no_deployment_base, caplog):
    with caplog.at_level(logging.WARNING, logger="cast.migrations"):
        run([{"site_id": 7, "api_base": "https://[broken", "api_token": ""}])
    [record] = caplog.records
    message = record.getMessage()
    assert "<unparseable URL>" in message
    assert "stays disabled until CAST_VOXHELM_API_BASE is set" in message
    assert "token" not in message.split("deploy config.")[-1]


def test_migration_uses_environment_base_when_django_pair_is_empty(no_deployment_base, monkeypatch, caplog):
    monkeypatch.setenv("CAST_VOXHELM_API_BASE", "https://env.example/")
    with caplog.at_level(logging.WARNING, logger="cast.migrations"):
        run([{"site_id": 1, "api_base": "https://env.example", "api_token": ""}])
    assert caplog.records == []


def test_reverse_migration_is_a_noop():
    operation = migration.Migration.operations[0]
    assert operation.reverse_code is operation.noop


@pytest.mark.parametrize("value", ["", None])
def test_api_base_check_ignores_unset_base(no_deployment_base, settings, value):
    settings.CAST_VOXHELM_API_BASE = value
    assert check_cast_voxhelm_api_base() == []


def test_api_base_check_accepts_valid_base(settings):
    settings.CAST_VOXHELM_API_BASE = "https://voxhelm.example"
    assert check_cast_voxhelm_api_base() == []


@pytest.mark.parametrize("source", ["django", "env"])
def test_api_base_check_rejects_unsafe_base(no_deployment_base, settings, monkeypatch, source):
    unsafe = "https://user@voxhelm.example"
    if source == "django":
        settings.CAST_VOXHELM_API_BASE = unsafe
    else:
        monkeypatch.setenv("CAST_VOXHELM_API_BASE", unsafe)
    [error] = check_cast_voxhelm_api_base()
    assert error.id == "cast.E012"
    assert "credentials" in error.msg
