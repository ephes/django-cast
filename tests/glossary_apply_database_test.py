"""Glossary application selects and preflights synthetic database rows."""

from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.db import connections

from cast.models import Audio, Episode, Podcast, Transcript
from cast.transcripts.corrections import CorrectionsResult
from tests.repository.database_test import independent_podcasts, refuse_default  # noqa: F401

pytestmark = pytest.mark.usefixtures("independent_podcasts")


class PodcastRouter:
    def db_for_read(self, model, **hints):
        instance = hints.get("instance")
        return "migration_other" if instance is not None else "default"

    def db_for_write(self, model, **hints):
        if model is Podcast:
            return "migration_other"
        return self.db_for_read(model, **hints)


@pytest.mark.django_db(databases={"default", "migration_other"})
@pytest.mark.parametrize("dry_run", [False, True])
def test_podcast_selection_binds_transcripts_before_refresh(settings, monkeypatch, dry_run):
    from cast.management.commands import apply_transcript_glossary as command

    settings.DATABASE_ROUTERS = [PodcastRouter()]
    seen = []

    def refresh(transcript, *, dry_run):
        seen.append((transcript._state.db, transcript.audio.title, dry_run))
        return CorrectionsResult(status="synthetic")

    monkeypatch.setattr(command, "refresh_transcript_corrections", refresh)
    with connections["default"].execute_wrapper(refuse_default):
        call_command("apply_transcript_glossary", podcast="synthetic", dry_run=dry_run, stdout=StringIO())
    assert seen == [("migration_other", "migration_other", dry_run)]


@pytest.mark.django_db(databases={"default", "migration_other"})
@pytest.mark.parametrize("model", [Episode, Transcript, Audio])
@pytest.mark.parametrize("operation", ["read", "write"])
def test_apply_refuses_split_routing_before_artifact_access(settings, monkeypatch, model, operation):
    from cast.management.commands import apply_transcript_glossary as command

    class SplitRouter(PodcastRouter):
        def db_for_read(self, candidate, **hints):
            if operation == "read" and candidate is model:
                return "default"
            return super().db_for_read(candidate, **hints)

        def db_for_write(self, candidate, **hints):
            if operation == "write" and candidate is model:
                return "default"
            # Don't accidentally split writes in a read-only mismatch test.
            return "migration_other"

    settings.DATABASE_ROUTERS = [SplitRouter()]

    def refuse(*args, **kwargs):
        pytest.fail("Routing must be checked before any artifact access")

    monkeypatch.setattr(command, "refresh_transcript_corrections", refuse)
    with pytest.raises(CommandError, match="database"):
        call_command("apply_transcript_glossary", podcast="synthetic", stdout=StringIO())


@pytest.mark.django_db(databases={"default", "migration_other"})
@pytest.mark.parametrize("operation", ["read", "write"])
def test_apply_preflights_actual_transcript_routes(settings, monkeypatch, operation):
    from cast.management.commands import apply_transcript_glossary as command

    class InstanceRouter(PodcastRouter):
        def db_for_read(self, model, **hints):
            if operation == "read" and isinstance(hints.get("instance"), Transcript) and model is Transcript:
                return "default"
            return super().db_for_read(model, **hints)

        def db_for_write(self, model, **hints):
            if operation == "write" and isinstance(hints.get("instance"), Transcript) and model is Transcript:
                return "default"
            return super().db_for_write(model, **hints)

    settings.DATABASE_ROUTERS = [InstanceRouter()]

    def refuse(*args, **kwargs):
        pytest.fail("Actual transcript routes must be checked before artifact access")

    monkeypatch.setattr(command, "refresh_transcript_corrections", refuse)
    with pytest.raises(CommandError, match="database"):
        call_command("apply_transcript_glossary", podcast="synthetic", stdout=StringIO())


@pytest.mark.django_db(databases={"default", "migration_other"})
@pytest.mark.parametrize("dry_run", [False, True])
def test_explicit_selection_preflights_later_transcript(settings, mocker, dry_run):
    first = Transcript.objects.using("default").get()
    audio = Audio.objects.create(title="second", collection=first.collection, user=first.audio.user)
    second = Transcript.objects.create(pk=first.pk + 1, audio=audio, collection=first.collection)

    class InstanceRouter:
        def db_for_write(self, model, **hints):
            instance = hints.get("instance")
            if model is Transcript and isinstance(instance, Transcript) and instance.pk == second.pk:
                return "migration_other"
            return None

    settings.DATABASE_ROUTERS = [InstanceRouter()]
    refresh = mocker.patch("cast.management.commands.apply_transcript_glossary.refresh_transcript_corrections")

    with pytest.raises(CommandError, match="one database for transcript reads and writes"):
        call_command(
            "apply_transcript_glossary", "--transcript", str(first.pk), "--transcript", str(second.pk), dry_run=dry_run
        )

    refresh.assert_not_called()
