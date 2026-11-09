"""The generic ``File`` model is removed; its table is only dropped when empty."""

import importlib
from types import SimpleNamespace

import pytest
from django.apps import apps as django_apps
from django.contrib.admin.sites import site as admin_site

from cast.models.file import validate_file_extension

migration = importlib.import_module("cast.migrations.0090_remove_file")


class Rows:
    def __init__(self, count):
        self._count = count
        self.alias = None

    def using(self, alias):
        self.alias = alias
        return self

    def count(self):
        return self._count


def run(count):
    objects = Rows(count)
    model = SimpleNamespace(objects=objects)
    fake_apps = SimpleNamespace(get_model=lambda app, name: (app, name) == ("cast", "File") and model)
    migration.refuse_if_files_exist(fake_apps, SimpleNamespace(connection=SimpleNamespace(alias="other")))
    assert objects.alias == "other"


def test_migration_drops_an_empty_table():
    run(0)


def test_migration_refuses_while_rows_exist():
    with pytest.raises(RuntimeError, match=r"cast\.File still has 2 row\(s\).*DELETE FROM cast_file"):
        run(2)


def test_migration_deletes_the_model_after_the_guard():
    guard, delete = migration.Migration.operations
    assert guard.code is migration.refuse_if_files_exist
    assert delete.name == "File"


def test_model_and_admin_are_gone():
    with pytest.raises(LookupError):
        django_apps.get_model("cast", "File")
    registered = {(model._meta.app_label, model._meta.model_name) for model in admin_site._registry}
    assert ("cast", "file") not in registered


def test_historical_migration_validator_stays_importable_and_accepts_anything():
    assert validate_file_extension(object()) is None
