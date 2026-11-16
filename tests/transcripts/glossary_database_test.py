"""Glossary imports stay atomic on one synthetic database alias."""

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.management import CommandError
from django.db import connections
from wagtail.models import Locale, Page

from cast.models import Podcast, TranscriptGlossaryTerm
from tests.import_transcript_glossary_command_helpers import run, write_json


class GlossaryRouter:
    def db_for_read(self, model, **hints):
        return "migration_other"

    db_for_write = db_for_read


@pytest.fixture
def routed_podcast(settings):
    settings.DATABASE_ROUTERS = [GlossaryRouter()]
    ContentType.objects.clear_cache()
    locale = Locale.objects.create(language_code="en")
    root = Page.add_root(instance=Page(title="Synthetic root", slug="root", locale=locale))
    podcast = root.add_child(instance=Podcast(title="Synthetic podcast", slug="synthetic", locale=locale))
    yield podcast
    ContentType.objects.clear_cache()


def refuse_default(execute, sql, params, many, context):
    raise AssertionError(f"Import touched default: {sql}")


@pytest.mark.django_db(databases={"default", "migration_other"})
@pytest.mark.parametrize("dry_run", [True, False])
def test_routed_import_uses_one_alias(routed_podcast, tmp_path, dry_run):
    term = TranscriptGlossaryTerm.objects.create(podcast=routed_podcast, term="Synthetica", variants="Old Variant")
    path = write_json(tmp_path, [{"term": "Synthetica", "variants": ["New Variant"]}, {"term": "Frobnicator"}])
    with connections["default"].execute_wrapper(refuse_default):
        stdout, stderr = run(routed_podcast.slug, path, dry_run=dry_run)
    assert "created=1 updated=1" in stdout and not stderr
    term.refresh_from_db()
    assert term.variants == ("Old Variant" if dry_run else "New Variant")
    assert TranscriptGlossaryTerm.objects.count() == (1 if dry_run else 2)
    assert not TranscriptGlossaryTerm.objects.using("default").exists()


@pytest.mark.django_db(databases={"default", "migration_other"})
def test_routed_import_failure_rolls_back_updates_and_inserts(routed_podcast, tmp_path, monkeypatch):
    term = TranscriptGlossaryTerm.objects.create(podcast=routed_podcast, term="Synthetica", notes="old")
    save = TranscriptGlossaryTerm.save

    def fail(instance, *args, **kwargs):
        if instance.term == "Failure":
            raise RuntimeError("Synthetic failure")
        return save(instance, *args, **kwargs)

    monkeypatch.setattr(TranscriptGlossaryTerm, "save", fail)
    path = write_json(tmp_path, [{"term": "Synthetica", "notes": "new"}, {"term": "Created"}, {"term": "Failure"}])
    with pytest.raises(RuntimeError, match="Synthetic failure"):
        run(routed_podcast.slug, path)
    term.refresh_from_db()
    assert term.notes == "old"
    assert TranscriptGlossaryTerm.objects.count() == 1
    assert not TranscriptGlossaryTerm.objects.using("default").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("split", ["lock", "term", "read", "instance", "language"])
def test_import_refuses_split_router_decisions(podcast, settings, tmp_path, split):
    class SplitRouter:
        def db_for_write(self, model, **hints):
            if (split == "lock" and model is Page) or (split == "term" and model is TranscriptGlossaryTerm):
                return "migration_other"
            if split == "instance" and isinstance(hints.get("instance"), TranscriptGlossaryTerm):
                return "migration_other"
            return "default"

        def db_for_read(self, model, **hints):
            if (split == "read" and model is TranscriptGlossaryTerm) or (split == "language" and model is Locale):
                return "migration_other"
            return "default"

    settings.DATABASE_ROUTERS = [SplitRouter()]
    with pytest.raises(CommandError, match="database"):
        run(podcast.slug, write_json(tmp_path, [{"term": "Synthetica"}]))
    assert not TranscriptGlossaryTerm.objects.using("default").exists()


def test_import_refuses_unknown_database(settings):
    from cast.management.commands.import_transcript_glossary import Command

    class UnknownRouter:
        def db_for_write(self, model, **hints):
            return "unknown"

    settings.DATABASE_ROUTERS = [UnknownRouter()]
    with pytest.raises(CommandError, match="unknown database"):
        Command.get_podcast("synthetic")


@pytest.mark.django_db(databases={"default", "migration_other"})
def test_routed_import_validates_cross_term_conflicts(routed_podcast, tmp_path):
    TranscriptGlossaryTerm.objects.create(podcast=routed_podcast, term="Existing", variants="Shared Variant")
    path = write_json(tmp_path, [{"term": "Synthetica", "variants": ["Shared Variant"]}, {"term": "Valid"}])
    with connections["default"].execute_wrapper(refuse_default):
        stdout, stderr = run(routed_podcast.slug, path)
    assert "created=1" in stdout and "skipped=1" in stdout
    assert 'already a variant of "Existing"' in stderr
    assert not TranscriptGlossaryTerm.objects.filter(term="Synthetica").exists()
