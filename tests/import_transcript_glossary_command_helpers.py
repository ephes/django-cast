"""Shared test data and setup helpers."""

import json
from io import StringIO

from django.core.management import call_command


def write_json(tmp_path, data):
    path = tmp_path / "glossary.json"
    path.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")
    return str(path)


def run(*args, **options):
    stdout, stderr = StringIO(), StringIO()
    call_command("import_transcript_glossary", *args, stdout=stdout, stderr=stderr, **options)
    return stdout.getvalue(), stderr.getvalue()
