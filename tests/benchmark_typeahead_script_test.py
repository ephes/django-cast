"""The typeahead benchmark seeder must not touch a database that is not a benchmark database."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.db.migrations.recorder import MigrationRecorder
from wagtail.models import Collection, Locale, Page, Site

from cast.models import Blog, Post

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def script(settings, mocker):
    """The benchmark module under its own settings contract, with ``migrate`` replaced."""
    from scripts import benchmark_typeahead

    settings.SETTINGS_MODULE = "scripts.typeahead_benchmark_settings"
    migrate = mocker.patch.object(benchmark_typeahead, "call_command")
    return benchmark_typeahead, migrate


@pytest.fixture()
def migrated_db(db):
    """The test database is built without migrations; a migrated one has their bookkeeping table."""
    # Plain SQL inside the test transaction: SQLite's schema editor cannot run there.
    with connection().cursor() as cursor:
        cursor.execute(
            "CREATE TABLE django_migrations (id integer PRIMARY KEY, app varchar(255) NOT NULL, "
            "name varchar(255) NOT NULL, applied timestamp NOT NULL)"
        )


def database_state():
    return {
        "sites": list(Site.objects.order_by("pk").values_list("pk", "hostname", "root_page_id", "is_default_site")),
        "users": list(get_user_model().objects.order_by("pk").values_list("pk", "username")),
        "pages": list(Page.objects.order_by("path").values_list("pk", "path", "slug", "title", "numchild")),
        "collections": Collection.objects.count(),
        "locales": list(Locale.objects.order_by("pk").values_list("language_code", flat=True)),
        "migrations": MigrationRecorder.Migration.objects.count()
        if MigrationRecorder(connection()).has_table()
        else 0,
    }


def connection():
    from django.db import connection as default_connection

    return default_connection


def assert_refused_without_changes(script, match):
    benchmark, migrate = script
    before = database_state()

    with pytest.raises(RuntimeError, match=match):
        benchmark.seed([2])

    migrate.assert_not_called()
    assert database_state() == before
    assert not get_user_model().objects.filter(username="typeahead-benchmark").exists()
    assert not Blog.objects.filter(slug__startswith="typeahead-benchmark-").exists()


def test_seed_refuses_a_real_site_before_migrating_or_writing(script, migrated_db, blog, site):
    # A real project: its Blog is the default Site's root page, not the tree root.
    site.root_page = blog
    site.save(update_fields=["root_page"])

    assert_refused_without_changes(script, "non-benchmark Blogs: test_blog")

    site.refresh_from_db()
    assert site.root_page_id == blog.pk


def test_seed_refuses_pages_and_users_of_a_site_without_blogs(script, migrated_db, site, user):
    home = site.root_page.add_child(instance=Page(title="Company", slug="company"))
    home.add_child(instance=Page(title="About", slug="about"))

    assert_refused_without_changes(
        script,
        r"pages outside the benchmark Blogs: company, about; 1 user account\(s\) other than typeahead-benchmark",
    )


def test_seed_refuses_a_database_with_user_accounts_only(script, migrated_db, user):
    assert_refused_without_changes(script, r"1 user account\(s\) other than typeahead-benchmark\. Nothing was changed")


STOCK_HOME = {"title": "Welcome to your new Wagtail site!", "slug": "home"}


def add_home_page(**changes):
    locale, _created = Locale.objects.get_or_create(language_code="en")
    root = Page.get_first_root_node() or Page.add_root(instance=Page(title="Root", slug="root", locale=locale))
    home = root.add_child(instance=Page(**{**STOCK_HOME, **changes}))
    Site.objects.all().delete()
    Site.objects.create(hostname="localhost", port=80, root_page=home, is_default_site=True)
    return root, home


@pytest.mark.parametrize(
    "changes",
    [
        {"title": "Company homepage"},
        {"seo_title": "Company"},
        {"search_description": "What we do"},
        {"title": "Company homepage", "seo_title": "Company", "search_description": "What we do"},
    ],
)
def test_seed_refuses_an_edited_home_page(script, migrated_db, changes):
    _root, home = add_home_page(**changes)

    assert_refused_without_changes(script, "pages outside the benchmark Blogs: home")

    assert Site.objects.get(is_default_site=True).root_page_id == home.pk


def test_seed_refuses_a_home_page_with_a_saved_revision(script, migrated_db):
    _root, home = add_home_page()
    home.save_revision()

    assert_refused_without_changes(script, "pages outside the benchmark Blogs: home")


def test_seed_refuses_a_home_page_with_children(script, migrated_db):
    _root, home = add_home_page()
    home.add_child(instance=Page(title="Imprint", slug="imprint"))

    assert_refused_without_changes(script, "pages outside the benchmark Blogs: home, imprint")


def test_preflight_refuses_a_database_with_foreign_tables_only(script, mocker):
    benchmark, migrate = script
    mocker.patch.object(benchmark.connection.introspection, "table_names", return_value=["customer_invoice"])

    with pytest.raises(RuntimeError, match="tables without the benchmark schema"):
        benchmark.seed([2])

    migrate.assert_not_called()


@pytest.mark.parametrize(
    "foreign", ["customer_invoice", "auth_user_customer_invoice", "wagtailsearch_indexentry_fts_export"]
)
def test_seed_refuses_foreign_tables_next_to_the_benchmark_schema(script, migrated_db, foreign):
    benchmark, _migrate = script
    tables = connection().introspection.table_names()
    # The FTS tables Wagtail's SQLite search migration creates are part of the schema.
    assert benchmark.non_benchmark_content({*tables, *benchmark.SEARCH_INDEX_TABLES}) == []

    with patch.object(benchmark.connection.introspection, "table_names", return_value=[*tables, foreign]):
        assert_refused_without_changes(script, f"tables that do not belong to the benchmark schema: {foreign}")


def test_seed_refuses_a_schema_this_project_did_not_migrate(script, db):
    # Model tables exist, but no migration was ever recorded in this database.
    assert not MigrationRecorder(connection()).has_table()
    benchmark, migrate = script

    with pytest.raises(RuntimeError, match=r"tables without the benchmark schema \(missing django_migrations\)"):
        benchmark.seed([2])

    migrate.assert_not_called()


def test_seed_refuses_other_settings_before_touching_the_database(script, settings):
    # No database fixture: any query would fail this test with a different error.
    benchmark, migrate = script
    settings.SETTINGS_MODULE = "config.settings.production"

    with pytest.raises(RuntimeError, match="Refusing to seed with DJANGO_SETTINGS_MODULE=config.settings.production"):
        benchmark.seed([2])

    migrate.assert_not_called()


def test_seed_refuses_a_database_it_cannot_inspect(script, migrated_db, mocker):
    benchmark, migrate = script
    mocker.patch.object(benchmark, "non_benchmark_content", side_effect=DatabaseError("no such column"))
    before = database_state()

    with pytest.raises(RuntimeError, match="could not be checked for existing content"):
        benchmark.seed([2])

    migrate.assert_not_called()
    assert database_state() == before


def test_isolated_database_seeds_and_can_be_seeded_again(script, migrated_db):
    benchmark, migrate = script

    benchmark.seed([2])

    migrate.assert_called_once_with("migrate", interactive=False, verbosity=0)
    blog = Blog.objects.get(slug="typeahead-benchmark-2")
    assert blog.unfiltered_published_posts.count() == 2
    assert Post.objects.child_of(blog).count() == 3  # plus the restricted control
    assert Site.objects.get(is_default_site=True).root_page_id == Page.get_first_root_node().pk
    assert list(get_user_model().objects.values_list("username", flat=True)) == ["typeahead-benchmark"]

    # The seeded database is recognised as a benchmark database: adding a size works.
    benchmark.seed([2, 1])

    assert migrate.call_count == 2
    assert Blog.objects.filter(slug__startswith="typeahead-benchmark-").count() == 2
    assert benchmark.non_benchmark_content(set(connection().introspection.table_names())) == []


def test_freshly_migrated_database_with_default_home_page_seeds(script, migrated_db):
    benchmark, _migrate = script
    root, _home = add_home_page()

    benchmark.seed([1])

    assert Site.objects.get(is_default_site=True).root_page_id == root.pk
    assert Blog.objects.get(slug="typeahead-benchmark-1").unfiltered_published_posts.count() == 1


def test_empty_database_without_tables_passes_the_preflight(script, mocker):
    benchmark, _migrate = script
    mocker.patch.object(benchmark.connection.introspection, "table_names", return_value=[])

    benchmark.preflight_benchmark_database()


def run_script(tmp_path, *args, **env):
    environment = {key: value for key, value in os.environ.items() if not key.startswith(("DJANGO_", "CAST_"))}
    environment.update(env)
    return subprocess.run(
        [sys.executable, "-m", "scripts.benchmark_typeahead", *args],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=300,
    )


@pytest.mark.slow
def test_command_line_seeds_a_fresh_database_and_refuses_a_foreign_one(tmp_path):
    """The real entry point with real migrations on throwaway SQLite files."""
    database = tmp_path / "benchmark.sqlite3"

    first = run_script(tmp_path, "seed", "--sizes", "1", CAST_BENCHMARK_DB_NAME=str(database))
    again = run_script(tmp_path, "seed", "--sizes", "1", CAST_BENCHMARK_DB_NAME=str(database))

    assert first.returncode == 0, first.stderr
    assert again.returncode == 0, again.stderr
    assert "typeahead-benchmark-1 already has 1 posts" in again.stderr

    # Someone else's content appears in the database: the next run changes nothing.
    with sqlite3.connect(database) as raw:
        raw.execute("UPDATE wagtailcore_page SET slug = 'my-real-blog' WHERE slug = 'typeahead-benchmark-1'")
        raw.execute("UPDATE wagtailcore_site SET root_page_id = (SELECT id FROM wagtailcore_page WHERE slug = 'home')")
    before = database.read_bytes()

    refused = run_script(tmp_path, "seed", "--sizes", "1", CAST_BENCHMARK_DB_NAME=str(database))

    assert refused.returncode != 0
    assert "non-benchmark Blogs: my-real-blog" in refused.stderr
    assert database.read_bytes() == before

    # An exported settings module of another project is not overridden but rejected.
    other = tmp_path / "other.sqlite3"
    wrong_settings = run_script(
        tmp_path, "seed", "--sizes", "1", DJANGO_SETTINGS_MODULE="tests.settings", CAST_TEST_DB=str(other)
    )

    assert wrong_settings.returncode != 0
    assert "Refusing to seed with DJANGO_SETTINGS_MODULE=tests.settings" in wrong_settings.stderr
    assert not other.exists()
