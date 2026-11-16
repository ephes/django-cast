"""Admission regressions for glossary maintenance commands."""

import os

import pytest
from django.core.management import CommandError, call_command

from cast.management.commands.import_transcript_glossary import Command
from cast.models import TranscriptGlossaryTerm


@pytest.mark.parametrize("kind", ["fifo", "directory", "device"])
def test_only_opened_regular_files_are_admitted(tmp_path, mocker, kind):
    path = tmp_path / "source"
    if kind == "fifo":
        os.mkfifo(path)
        # Catch the old blocking open without hanging the regression runner.
        mocker.patch("pathlib.Path.open", side_effect=AssertionError("blocking open"))
    elif kind == "directory":
        path.mkdir()
    else:
        path = "/dev/null"
    with pytest.raises(CommandError, match="regular file"):
        Command.load_entries(str(path))


def test_regular_symlinks_and_exact_byte_limit(tmp_path, monkeypatch):
    from cast.management.commands import import_transcript_glossary as command

    path = tmp_path / "source"
    path.write_bytes(b"[]  ")
    link = tmp_path / "link"
    link.symlink_to(path)
    monkeypatch.setattr(command, "MAX_INPUT_BYTES", 4)
    assert Command.load_entries(str(link)) == []
    path.write_bytes(b"[]   ")
    with pytest.raises(CommandError, match="exceeds"):
        Command.load_entries(str(link))


@pytest.mark.django_db
@pytest.mark.parametrize(
    "content",
    [
        '[{"term":"Old","term":"New"}]',
        '[{"term":"Old","notes":"x","n\\u006ftes":"x"}]',
        '[{"term":"Old","variants":{"nested":1,"nested":2}}]',
    ],
)
def test_duplicate_members_refuse_entire_document(podcast, tmp_path, content):
    term = TranscriptGlossaryTerm.objects.create(podcast=podcast, term="Old", notes="preserved")
    path = tmp_path / "source.json"
    path.write_text(content)
    with pytest.raises(CommandError, match="duplicate JSON member"):
        call_command("import_transcript_glossary", podcast.slug, str(path))
    term.refresh_from_db()
    assert term.notes == "preserved" and term.term == "Old"


@pytest.mark.django_db
@pytest.mark.parametrize("identifier", ["²", "١", "0", "-1", "01", str(2**63), "9" * 5000])
@pytest.mark.parametrize("command", ["import_transcript_glossary", "apply_transcript_glossary"])
def test_invalid_podcast_ids_fail_before_queries(identifier, command, django_assert_num_queries):
    with django_assert_num_queries(0), pytest.raises(CommandError, match="positive.*ID") as error:
        if command == "import_transcript_glossary":
            call_command(command, identifier, "unused.json")
        else:
            call_command(command, podcast=identifier)
    assert len(str(error.value)) < 200


@pytest.mark.django_db
@pytest.mark.parametrize("identifier", [0, -1, 2**63, "²", "9" * 5000, True, 1.5])
def test_invalid_transcript_ids_fail_before_queries(identifier, django_assert_num_queries):
    with django_assert_num_queries(0), pytest.raises(CommandError, match="positive.*ID"):
        call_command("apply_transcript_glossary", transcripts=[identifier])


@pytest.mark.django_db
def test_unknown_explicit_transcript_is_an_error():
    with pytest.raises(CommandError, match="Unknown transcript"):
        call_command("apply_transcript_glossary", transcripts=[999999])


@pytest.mark.parametrize("regular", [False, True])
def test_opened_descriptor_is_closed_on_acceptance_and_refusal(tmp_path, mocker, regular):
    from cast.management.commands import import_transcript_glossary as command

    path = tmp_path / "source"
    if regular:
        path.write_text("[]")
    else:
        os.mkfifo(path)
    opened = mocker.spy(command.os, "open")
    closed = mocker.spy(command.os, "close")
    if regular:
        assert Command.load_entries(str(path)) == []
    else:
        with pytest.raises(CommandError, match="regular"):
            Command.load_entries(str(path))
    closed.assert_called_once_with(opened.spy_return)


@pytest.mark.django_db
@pytest.mark.parametrize("model_name,internal_type", [("Podcast", "AutoField"), ("Transcript", "BigAutoField")])
def test_selector_uses_underlying_integer_field_range(model_name, internal_type, mocker, django_assert_num_queries):
    from django.db import connection

    from cast import models
    from cast.management.commands._selectors import positive_id

    model = getattr(models, model_name)
    # SQLite accepts all integers as int64 and hides relational PK metadata.
    # Exercise the strict public backend range table used by PostgreSQL.
    range_lookup = mocker.patch.object(
        connection.ops, "integer_field_range", side_effect=connection.ops.integer_field_ranges.__getitem__
    )
    _lower, upper = connection.ops.integer_field_ranges[internal_type]
    with django_assert_num_queries(0):
        assert positive_id(str(upper), model) == upper
        with pytest.raises(CommandError, match="positive.*ID"):
            positive_id(str(upper + 1), model)
    assert all(call.args == (internal_type,) for call in range_lookup.call_args_list)


@pytest.mark.django_db
def test_unknown_selection_does_not_process_its_valid_transcripts(audio, mocker):
    from cast.models import Transcript

    transcript = Transcript.objects.create(audio=audio)
    refresh = mocker.patch("cast.management.commands.apply_transcript_glossary.refresh_transcript_corrections")
    with pytest.raises(CommandError, match="Unknown transcript"):
        call_command("apply_transcript_glossary", "--transcript", str(transcript.pk), "--transcript", "999999")
    refresh.assert_not_called()
