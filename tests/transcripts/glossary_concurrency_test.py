"""Concurrent glossary additions use only synthetic rows and artifacts."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import close_old_connections, connection
from wagtail.models import Collection

from cast.models import Audio, Contributor, EpisodeContributor, TranscriptGlossaryTerm
from cast.transcripts import corrections
from tests.factories import EpisodeFactory, PodcastFactory
from tests.transcripts.corrections_test import make_transcript


@pytest.fixture
def shared_glossary(pg_editor_actors, settings, target):
    user, blog = pg_editor_actors
    settings.CAST_VOXHELM_LANGUAGE = "en"
    podcast = PodcastFactory(parent=blog.get_parent(), owner=user, title="Synthetic show", slug="synthetic-show")
    contributor = Contributor.objects.create(
        display_name="Synthetica Person", slug="synthetica", transcript_variants="Synth Original"
    )
    other_show = podcast
    if target == "contributor-other-show":
        other_show = PodcastFactory(parent=blog.get_parent(), owner=user, title="Second show", slug="second-show")
    transcripts = []
    for index in range(2):
        audio = Audio.objects.create(
            user=user, collection=Collection.get_first_root_node(), title=f"Synthetic {index}"
        )
        episode = EpisodeFactory(
            parent=other_show if index else podcast,
            owner=user,
            title=f"Episode {index}",
            slug=f"episode-{index}",
            podcast_audio=audio,
        )
        EpisodeContributor.objects.create(episode=episode, contributor=contributor, role=EpisodeContributor.ROLE_GUEST)
        transcripts.append(make_transcript(audio, texts=[(1000, "Synthetica Person uses Frobnicator.")]))
    return podcast, contributor, transcripts


@pytest.mark.parametrize("target", ["contributor", "contributor-other-show", "term", "new-term"])
def test_two_glossary_additions_preserve_both_variants(shared_glossary, monkeypatch, target):
    podcast, contributor, transcripts = shared_glossary
    canonical = contributor.display_name if target.startswith("contributor") else "Frobnicator"
    if target == "term":
        TranscriptGlossaryTerm.objects.create(podcast=podcast, term=canonical, variants="Frob Original")
    model = Contributor if target.startswith("contributor") else TranscriptGlossaryTerm
    field = "transcript_variants" if target.startswith("contributor") else "variants"
    original_save = model.save
    first_prepared = threading.Event()
    second_prepared = threading.Event()
    second_started = threading.Event()
    release = threading.Event()

    def pause_save(self, *args, **kwargs):
        value = getattr(self, field)
        if "Synthetic Variant One" in value and "Synthetic Variant Two" not in value:
            first_prepared.set()
            assert release.wait(10)
        elif "Synthetic Variant Two" in value:
            second_prepared.set()
        return original_save(self, *args, **kwargs)

    monkeypatch.setattr(model, "save", pause_save)

    def add(index, variant):
        close_old_connections()
        try:
            if index:
                second_started.set()
            corrections.add_original_to_glossary(transcripts[index], variant, canonical)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(add, 0, "Synthetic Variant One")
        try:
            assert first_prepared.wait(10)
            second = pool.submit(add, 1, "Synthetic Variant Two")
            assert second_started.wait(10)
            assert not second_prepared.wait(0.2), "Second append used a snapshot before the first append committed"
        finally:
            release.set()
        first.result(timeout=20)
        second.result(timeout=20)
    row = (
        Contributor.objects.get(pk=contributor.pk)
        if target.startswith("contributor")
        else TranscriptGlossaryTerm.objects.get(podcast=podcast, term=canonical)
    )
    assert {"Synthetic Variant One", "Synthetic Variant Two"} <= set(getattr(row, field).splitlines())
    if not target.startswith("contributor"):
        assert TranscriptGlossaryTerm.objects.filter(podcast=podcast, term=canonical).count() == 1


@pytest.mark.skipif(
    connection.vendor != "postgresql", reason="Requires independent PostgreSQL read/write transactions"
)
@pytest.mark.parametrize("field", ["notes", "variants"])
def test_import_detects_concurrent_owned_edits_and_preserves_omitted_notes(
    pg_editor_actors, tmp_path, monkeypatch, field
):
    from tests.import_transcript_glossary_command_test import run, write_json

    user, blog = pg_editor_actors
    podcast = PodcastFactory(parent=blog.get_parent(), owner=user, title="Synthetic import", slug="synthetic-import")
    term = TranscriptGlossaryTerm.objects.create(podcast=podcast, term="Frobnicator", variants="Frob Old", notes="old")
    original_clean = TranscriptGlossaryTerm.full_clean
    edited = []

    def edit():
        close_old_connections()
        try:
            TranscriptGlossaryTerm.objects.filter(pk=term.pk).update(**{field: "Concurrent Edit"})
        finally:
            close_old_connections()

    def clean(instance, *args, **kwargs):
        original_clean(instance, *args, **kwargs)
        if instance.pk == term.pk and not edited:
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(edit).result(timeout=10)
            edited.append(True)

    monkeypatch.setattr(TranscriptGlossaryTerm, "full_clean", clean)
    stdout, stderr = run(podcast.slug, write_json(tmp_path, [{"term": "Frobnicator", "variants": ["Frob New"]}]))
    assert edited
    term.refresh_from_db()
    assert getattr(term, field) == "Concurrent Edit"
    if field == "notes":
        assert "updated=1" in stdout
        assert term.variants == "Frob New"
        assert not stderr
    else:
        assert "skipped=1" in stdout
        assert "concurrent edit" in stderr


@pytest.mark.skipif(
    connection.vendor != "postgresql", reason="Requires independent PostgreSQL read/write transactions"
)
def test_import_concurrent_insert_keeps_outer_transaction_usable(pg_editor_actors, tmp_path, monkeypatch):
    from tests.import_transcript_glossary_command_test import run, write_json

    user, blog = pg_editor_actors
    podcast = PodcastFactory(parent=blog.get_parent(), owner=user, title="Synthetic insert", slug="synthetic-insert")
    original_clean = TranscriptGlossaryTerm.full_clean
    raced = []

    def insert():
        close_old_connections()
        try:
            TranscriptGlossaryTerm.objects.create(podcast=podcast, term="Frobnicator", notes="concurrent")
        finally:
            close_old_connections()

    def clean(instance, *args, **kwargs):
        original_clean(instance, *args, **kwargs)
        if instance.term == "Frobnicator" and not raced:
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(insert).result(timeout=10)
            raced.append(True)

    monkeypatch.setattr(TranscriptGlossaryTerm, "full_clean", clean)
    path = write_json(tmp_path, [{"term": "Frobnicator"}, {"term": "Synthetica"}])
    stdout, stderr = run(podcast.slug, path)
    assert raced
    assert "created=1" in stdout and "skipped=1" in stdout
    assert "concurrent edit" in stderr
    assert TranscriptGlossaryTerm.objects.get(term="Frobnicator").notes == "concurrent"
    assert TranscriptGlossaryTerm.objects.filter(term="Synthetica").exists()


@pytest.mark.skipif(connection.vendor != "postgresql", reason="Requires independent PostgreSQL transactions")
def test_imports_serialize_cross_term_variants_per_podcast(pg_editor_actors, tmp_path, monkeypatch):
    from cast.management.commands.import_transcript_glossary import Command
    from tests.import_transcript_glossary_command_test import run, write_json

    user, blog = pg_editor_actors
    podcast = PodcastFactory(parent=blog.get_parent(), owner=user, title="Synthetic show", slug="synthetic-show")
    independent = PodcastFactory(parent=blog.get_parent(), owner=user, title="Other show", slug="other-show")
    for name in ("Frobnicator", "Synthetica"):
        TranscriptGlossaryTerm.objects.create(podcast=podcast, term=name)
    paths = []
    for index, name in enumerate(("Frobnicator", "Synthetica", "Independentia")):
        folder = tmp_path / str(index)
        folder.mkdir()
        paths.append(write_json(folder, [{"term": name, "variants": ["Synthetic Shared Variant"]}]))
    first_saved = threading.Event()
    second_started = threading.Event()
    second_read = threading.Event()
    release = threading.Event()
    role = threading.local()
    original_entry = Command.import_entry
    original_existing = Command.existing_terms

    def import_entry(*args, **kwargs):
        result = original_entry(*args, **kwargs)
        if role.index == 0:
            first_saved.set()
            assert release.wait(10)
        return result

    def existing_terms(show):
        if role.index == 1:
            second_read.set()
        return original_existing(show)

    monkeypatch.setattr(Command, "import_entry", staticmethod(import_entry))
    monkeypatch.setattr(Command, "existing_terms", staticmethod(existing_terms))

    def execute(index, show):
        close_old_connections()
        role.index = index
        try:
            if index == 1:
                second_started.set()
            return run(show.slug, paths[index])
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(execute, 0, podcast)
        try:
            assert first_saved.wait(10)
            second = pool.submit(execute, 1, podcast)
            assert second_started.wait(10)
            assert not second_read.wait(0.2), "Second import read the namespace before the first committed"
            # A different podcast must not wait for this podcast's namespace lock.
            third_out, third_err = pool.submit(execute, 2, independent).result(timeout=10)
            assert "created=1" in third_out and not third_err
        finally:
            release.set()
        first_out, first_err = first.result(timeout=20)
        second_out, second_err = second.result(timeout=20)
    assert "updated=1" in first_out and not first_err
    assert "skipped=1" in second_out and "already a variant" in second_err
    assert (
        TranscriptGlossaryTerm.objects.get(podcast=podcast, term="Frobnicator").variants == "Synthetic Shared Variant"
    )
    assert TranscriptGlossaryTerm.objects.get(podcast=podcast, term="Synthetica").variants == ""
