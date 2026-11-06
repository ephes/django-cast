"""Concurrent glossary additions use only synthetic rows and artifacts."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import close_old_connections
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
