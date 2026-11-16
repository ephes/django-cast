"""Import validation work scales with admitted terms, including skipped rows."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from cast.models import TranscriptGlossaryTerm, transcript_glossary as model
from cast.transcripts import glossary
from tests.import_transcript_glossary_command_helpers import run, write_json

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("count", [4, 40])
@pytest.mark.parametrize("invalid", [False, True])
def test_import_validation_has_linear_work(podcast, tmp_path, mocker, count, invalid):
    from cast.management.commands import import_transcript_glossary as command

    TranscriptGlossaryTerm.objects.bulk_create(
        [
            TranscriptGlossaryTerm(podcast=podcast, term=f"ExistingTerm{i}", variants=f"Existing Variant {i}")
            for i in range(count)
        ]
    )
    # The language word list has a fixed, one-time normalization cost.
    glossary.is_common_word("the", model.get_podcast_transcript_language(podcast))
    normalizers = [mocker.spy(module, "normalize_phrase") for module in (model, glossary, command)]
    language = mocker.spy(model, "get_podcast_transcript_language")
    entries = [
        {"term": f"ImportedTerm{i}", "variants": ["the" if invalid else f"Imported Variant {i}"]} for i in range(count)
    ]
    with CaptureQueriesContext(connection) as captured:
        stdout, stderr = run(podcast.slug, write_json(tmp_path, entries))
    scans = [
        q["sql"]
        for q in captured
        if q["sql"].startswith("SELECT")
        and '"cast_transcriptglossaryterm"."variants"' in q["sql"]
        and 'WHERE "cast_transcriptglossaryterm"."podcast_id" =' in q["sql"]
    ]
    assert len(scans) == 1
    assert language.call_count == 1
    assert sum(spy.call_count for spy in normalizers) <= 30 * (count * 2)
    assert f"{'skipped' if invalid else 'created'}={count}" in stdout
    assert bool(stderr) == invalid


@pytest.mark.parametrize("dry_run", [False, True])
def test_context_tracks_only_accepted_updates(podcast, tmp_path, dry_run):
    first = TranscriptGlossaryTerm.objects.create(podcast=podcast, term="First", variants="Released Variant")
    second = TranscriptGlossaryTerm.objects.create(podcast=podcast, term="Second", variants="Retained Variant")
    entries = [
        {"term": "First", "variants": ["New Variant"]},
        {"term": "Second", "variants": ["the"]},
        {"term": "Third", "variants": ["Released Variant"]},
        {"term": "Fourth", "variants": ["Retained Variant"]},
        {"term": "Fifth", "variants": ["New Variant"]},
    ]
    stdout, stderr = run(podcast.slug, write_json(tmp_path, entries), dry_run=dry_run)
    assert "created=1 updated=1 unchanged=0 skipped=3" in stdout
    assert 'already a variant of "Second"' in stderr
    assert 'already a variant of "First"' in stderr
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.variants == ("Released Variant" if dry_run else "New Variant")
    assert second.variants == "Retained Variant"
    assert TranscriptGlossaryTerm.objects.count() == (2 if dry_run else 3)


@pytest.mark.parametrize(
    ("term", "variants"),
    [
        ("Existing", ""),
        ("Held Variant", ""),
        ("New", "New\nExisting\nHeld Variant\nthe"),
        ("  New  Term ", "New Variant"),
    ],
)
def test_context_matches_standalone_validation(podcast, term, variants):
    from django.core.exceptions import ValidationError

    existing = TranscriptGlossaryTerm.objects.create(podcast=podcast, term="Existing", variants="Held Variant")
    context = model.GlossaryValidationContext.for_podcast(podcast, [existing])
    results = []
    for kwargs in ({}, {"validation_context": context}):
        candidate = TranscriptGlossaryTerm(podcast=podcast, term=term, variants=variants)
        try:
            candidate.full_clean(**kwargs)
        except ValidationError as exc:
            results.append(exc.message_dict)
        else:
            results.append({})
        assert candidate._validation_context is None
    assert results[0] == results[1]


def test_updating_one_owner_does_not_release_another_owners_variant(podcast):
    from django.core.exceptions import ValidationError

    first = TranscriptGlossaryTerm.objects.create(podcast=podcast, term="First", variants="Shared Variant")
    second = TranscriptGlossaryTerm.objects.create(podcast=podcast, term="Second", variants="Shared Variant")
    context = model.GlossaryValidationContext.for_podcast(podcast, [first, second])
    second.variants = "Different Variant"
    second.full_clean(validation_context=context)
    second.save()
    context.accept(second)
    candidate = TranscriptGlossaryTerm(podcast=podcast, term="Third", variants="Shared Variant")
    with pytest.raises(ValidationError, match='already a variant of "First"'):
        candidate.full_clean(validation_context=context)


def test_import_context_keeps_all_normalized_identity_collisions(podcast, tmp_path):
    # The database's Lower constraint permits these distinct stored spellings.
    TranscriptGlossaryTerm.objects.create(podcast=podcast, term="Same  Term", variants="First Reserved Variant")
    TranscriptGlossaryTerm.objects.create(podcast=podcast, term="same term", variants="Second Reserved Variant")
    stdout, stderr = run(
        podcast.slug, write_json(tmp_path, [{"term": "Other", "variants": ["First Reserved Variant"]}])
    )
    assert "skipped=1" in stdout
    assert 'already a variant of "Same  Term"' in stderr
    assert not TranscriptGlossaryTerm.objects.filter(term="Other").exists()
