import json
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from cast.models import TranscriptGlossaryTerm
from tests.factories import PodcastFactory


def write_json(tmp_path, data):
    path = tmp_path / "glossary.json"
    path.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")
    return str(path)


def run(*args, **options):
    stdout, stderr = StringIO(), StringIO()
    call_command("import_transcript_glossary", *args, stdout=stdout, stderr=stderr, **options)
    return stdout.getvalue(), stderr.getvalue()


@pytest.mark.django_db
class TestImportTranscriptGlossary:
    def test_creates_updates_and_skips(self, podcast, tmp_path):
        TranscriptGlossaryTerm.objects.create(podcast=podcast, term="gunicorn", variants="Gunacorn", notes="old")
        TranscriptGlossaryTerm.objects.create(podcast=podcast, term="Heroku", variants="Roku Cloud")
        path = write_json(
            tmp_path,
            [
                {"term": "Gunicorn", "variants": ["Gunacorn", "Gunna Corn"], "notes": "WSGI server"},
                {"term": "Heroku"},
                {"term": "Ruff", "variants": "Ruf\nrough"},
                {"term": "Jinja", "variants": "Jinjer"},
                {"term": "jinja", "variants": "Ginga"},
                "not an object",
                {"term": "  "},
                {"term": "Buttondown", "notes": 3},
                {"term": "Buttondown", "variants": [1]},
            ],
        )

        stdout, stderr = run(str(podcast.pk), path)

        assert stdout == "test podcast: created=1 updated=1 unchanged=1 skipped=6\n"
        assert stderr.splitlines() == [
            'skipped entry 3: "Ruff": variants: "rough" is a common word in this podcast\'s transcript language '
            "(en-us) and would be replaced everywhere. Leave it to the transcript review.",
            'skipped entry 5: "jinja": duplicate of entry 4',
            "skipped entry 6: an entry must be an object",
            'skipped entry 7: "term" must be a non-empty string',
            'skipped entry 8: "Buttondown": "notes" must be a string',
            'skipped entry 9: "Buttondown": "variants" must be a string or a list of strings',
        ]
        terms = {term.term: term for term in TranscriptGlossaryTerm.objects.filter(podcast=podcast)}
        assert sorted(terms) == ["Gunicorn", "Heroku", "Jinja"]
        assert terms["Gunicorn"].variant_list == ["Gunacorn", "Gunna Corn"]
        assert terms["Gunicorn"].notes == "WSGI server"
        assert terms["Heroku"].variants == "Roku Cloud"

    def test_dry_run_saves_nothing(self, podcast, tmp_path):
        path = write_json(tmp_path, [{"term": "Gunicorn", "variants": ["Gunacorn"]}])
        stdout, _stderr = run(podcast.slug, path, dry_run=True)
        assert stdout == "test podcast: created=1 updated=0 unchanged=0 skipped=0 (dry run, nothing saved)\n"
        assert not TranscriptGlossaryTerm.objects.exists()

    def test_entries_are_validated_against_each_other(self, podcast, tmp_path):
        path = write_json(tmp_path, [{"term": "Django", "variants": ["Jango"]}, {"term": "Jango"}])
        _stdout, stderr = run(podcast.slug, path)
        assert stderr == 'skipped entry 2: "Jango": term: "Jango" is a variant of the term "Django".\n'

    def test_podcast_lookup_errors(self, podcast, user, site, tmp_path):
        path = write_json(tmp_path, [])
        with pytest.raises(CommandError, match="No podcast with id 999999"):
            run("999999", path)
        with pytest.raises(CommandError, match='No podcast with slug "missing"'):
            run("missing", path)
        other_root = PodcastFactory(owner=user, title="root", slug="root_podcast", parent=site.root_page)
        PodcastFactory(owner=user, title="twin", slug="test_podcast", parent=other_root)
        with pytest.raises(CommandError, match="Several podcasts have the slug"):
            run("test_podcast", path)

    @pytest.mark.parametrize(("content", "message"), [("{", "Cannot read"), ('{"term": "x"}', "must contain")])
    def test_file_errors(self, podcast, tmp_path, content, message):
        with pytest.raises(CommandError, match=message):
            run(podcast.slug, write_json(tmp_path, content))
        with pytest.raises(CommandError, match="Cannot read"):
            run(podcast.slug, str(tmp_path / "missing.json"))


@pytest.mark.django_db
def test_import_source_read_is_bounded(podcast, monkeypatch, mocker):
    from io import BytesIO

    from cast.management.commands import import_transcript_glossary as command

    monkeypatch.setattr(command, "MAX_INPUT_BYTES", 64, raising=False)
    stream = BytesIO(b" " * 10000)
    read = mocker.spy(stream, "read")
    mocker.patch.object(command.Path, "open", return_value=stream)
    term = TranscriptGlossaryTerm.objects.create(podcast=podcast, term="Synthetica")
    with pytest.raises(CommandError, match="exceeds.*bytes"):
        run(podcast.slug, "misleading.json")
    read.assert_called_once_with(65)
    term.refresh_from_db()
    assert term.term == "Synthetica"
    assert TranscriptGlossaryTerm.objects.count() == 1


@pytest.mark.django_db
def test_import_entry_budget(podcast, tmp_path, monkeypatch):
    from cast.management.commands import import_transcript_glossary as command

    monkeypatch.setattr(command, "MAX_ENTRIES", 1, raising=False)
    path = write_json(tmp_path, [{"term": "Synthetica"}, {"term": "Frobnicator"}])
    with pytest.raises(CommandError, match="exceeds.*entries"):
        run(podcast.slug, path)
    assert not TranscriptGlossaryTerm.objects.exists()


@pytest.mark.parametrize("data", [b"\xff", b"[" * 2000])
def test_import_decode_failures_are_concise(tmp_path, data):
    from cast.management.commands.import_transcript_glossary import Command

    path = tmp_path / "invalid.json"
    path.write_bytes(data)
    with pytest.raises(CommandError, match="Cannot read") as error:
        Command.load_entries(str(path))
    assert len(str(error.value)) < 250


def test_import_diagnostics_keep_location_and_safe_read_reason(tmp_path, mocker):
    from cast.management.commands.import_transcript_glossary import Command

    with pytest.raises(CommandError, match="invalid JSON at line 1, column 2") as error:
        Command.load_entries(write_json(tmp_path, "{private-source"))
    assert "private-source" not in str(error.value)
    mocker.patch("pathlib.Path.open", side_effect=OSError(13, "Synthetic read refusal"))
    with pytest.raises(CommandError, match="Synthetic read refusal"):
        Command.load_entries("synthetic.json")


@pytest.mark.django_db
@pytest.mark.parametrize("count", [1, 20])
def test_import_builds_one_identity_index(podcast, tmp_path, count, django_assert_num_queries):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from cast.models.transcript_glossary import get_podcast_transcript_language

    get_podcast_transcript_language(podcast)  # control site/settings caches
    path = write_json(tmp_path, [{"term": f"SyntheticTerm{index}"} for index in range(count)])
    with CaptureQueriesContext(connection) as captured:
        stdout, stderr = run(podcast.slug, path)
    identity_queries = [
        q["sql"]
        for q in captured
        if q["sql"].startswith("SELECT")
        and '"cast_transcriptglossaryterm"."notes"' in q["sql"]
        and 'WHERE "cast_transcriptglossaryterm"."podcast_id" =' in q["sql"]
    ]
    assert len(identity_queries) == 1
    assert f"created={count}" in stdout
    assert not stderr
    assert TranscriptGlossaryTerm.objects.count() == count
    from cast.management.commands.import_transcript_glossary import Command

    with django_assert_num_queries(1):
        assert len(Command.existing_terms(podcast)) == count


@pytest.mark.django_db
@pytest.mark.parametrize("field", ["notes", "variants", "term"])
def test_import_preserves_omitted_edits_and_reports_owned_field_conflicts(podcast, tmp_path, monkeypatch, field):
    term = TranscriptGlossaryTerm.objects.create(podcast=podcast, term="Frobnicator", notes="old", variants="Frob Old")
    original_clean = TranscriptGlossaryTerm.full_clean
    edited = []

    def edit_during_validation(instance, *args, **kwargs):
        original_clean(instance, *args, **kwargs)
        if instance.pk == term.pk and not edited:
            edited.append(True)
            TranscriptGlossaryTerm.objects.filter(pk=term.pk).update(**{field: "Concurrent Edit"})

    monkeypatch.setattr(TranscriptGlossaryTerm, "full_clean", edit_during_validation)
    path = write_json(tmp_path, [{"term": "Frobnicator", "variants": ["Frob New"]}])
    stdout, stderr = run(podcast.slug, path)
    assert edited
    term.refresh_from_db()
    assert getattr(term, field) == "Concurrent Edit"
    if field == "notes":
        assert term.variants == "Frob New"
        assert "updated=1" in stdout
        assert not stderr
    else:
        assert "skipped=1" in stdout
        assert "concurrent edit" in stderr
        assert term.notes == "old"


@pytest.mark.django_db
def test_failed_import_validation_does_not_poison_identity_index(podcast, tmp_path):
    term = TranscriptGlossaryTerm.objects.create(podcast=podcast, term="Frobnicator", variants="Frob Old")
    path = write_json(tmp_path, [{"term": "Frobnicator", "variants": ["the"]}])
    stdout, _ = run(podcast.slug, path)
    assert "skipped=1" in stdout
    term.refresh_from_db()
    assert term.variants == "Frob Old"


@pytest.mark.django_db
@pytest.mark.parametrize("stage", ["validation", "insert"])
def test_import_reports_stale_create_conflicts_and_continues(podcast, tmp_path, monkeypatch, stage):
    original_clean = TranscriptGlossaryTerm.full_clean
    original_save = TranscriptGlossaryTerm.save
    raced = []

    def clean(instance, *args, **kwargs):
        if stage == "validation" and instance.term == "Frobnicator" and not raced:
            TranscriptGlossaryTerm.objects.create(podcast=podcast, term=instance.term, notes="concurrent")
            raced.append(True)
        original_clean(instance, *args, **kwargs)

    def save(instance, *args, **kwargs):
        if stage == "insert" and instance.term == "Frobnicator" and not raced:
            raced.append(True)
            original_save(TranscriptGlossaryTerm(podcast=podcast, term=instance.term, notes="competing insert"))
        return original_save(instance, *args, **kwargs)

    monkeypatch.setattr(TranscriptGlossaryTerm, "full_clean", clean)
    monkeypatch.setattr(TranscriptGlossaryTerm, "save", save)
    stdout, stderr = run(podcast.slug, write_json(tmp_path, [{"term": "Frobnicator"}, {"term": "Synthetica"}]))
    assert raced
    assert "created=1" in stdout and "skipped=1" in stdout
    assert "concurrent edit" in stderr
    assert TranscriptGlossaryTerm.objects.filter(term="Synthetica").exists()


@pytest.mark.django_db
def test_invalid_entry_leaves_index_instance_unchanged(podcast):
    from cast.management.commands.import_transcript_glossary import Command

    TranscriptGlossaryTerm.objects.create(podcast=podcast, term="Frobnicator", variants="Frob Old")
    existing = Command.existing_terms(podcast)
    outcome, _ = Command.import_entry(podcast, {"term": "Frobnicator", "variants": ["the"]}, 1, {}, existing)
    assert outcome == "skipped"
    assert existing["frobnicator"].variants == "Frob Old"


@pytest.mark.django_db
@pytest.mark.parametrize("dry_run", [False, True])
def test_notes_only_import_preserves_variants_and_dry_run(podcast, tmp_path, dry_run):
    term = TranscriptGlossaryTerm.objects.create(podcast=podcast, term="Frobnicator", variants="Frob Old", notes="old")
    stdout, stderr = run(
        podcast.slug, write_json(tmp_path, [{"term": "Frobnicator", "notes": "new"}]), dry_run=dry_run
    )
    assert "updated=1" in stdout and not stderr
    term.refresh_from_db()
    assert term.notes == ("old" if dry_run else "new")
    assert term.variants == "Frob Old"


@pytest.mark.django_db
def test_import_does_not_publish_into_a_concurrently_changed_podcast(podcast, tmp_path, monkeypatch):
    other = PodcastFactory(parent=podcast.get_parent(), owner=podcast.owner, title="Other show", slug="other-show")
    term = TranscriptGlossaryTerm.objects.create(podcast=podcast, term="Frobnicator", variants="Synthetic Old")
    TranscriptGlossaryTerm.objects.create(podcast=other, term="Synthetica", variants="Synthetic New")
    original_clean = TranscriptGlossaryTerm.full_clean
    moved = []

    def clean(instance, *args, **kwargs):
        original_clean(instance, *args, **kwargs)
        if instance.pk == term.pk and not moved:
            TranscriptGlossaryTerm.objects.filter(pk=term.pk).update(podcast=other)
            moved.append(True)

    monkeypatch.setattr(TranscriptGlossaryTerm, "full_clean", clean)
    stdout, stderr = run(podcast.slug, write_json(tmp_path, [{"term": "Frobnicator", "variants": ["Synthetic New"]}]))
    assert moved
    assert "skipped=1" in stdout and "concurrent edit" in stderr
    term.refresh_from_db()
    assert term.podcast_id == other.pk and term.variants == "Synthetic Old"
