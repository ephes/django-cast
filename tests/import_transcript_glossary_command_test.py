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
