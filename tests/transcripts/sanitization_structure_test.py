"""Pin the X3 module boundary and historical callable imports."""

import ast
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

from cast import transcript_sanitization as legacy

FORMAT_EXPORTS = {
    "podlove": ["apply_speaker_mapping_to_podlove_data", "sanitize_podlove_data", "podlove_contributors_from_data"],
    "dote": ["apply_speaker_mapping_to_dote_data", "sanitize_dote_data"],
    "webvtt": ["apply_speaker_mapping_to_webvtt_content", "sanitize_webvtt_content"],
}
VISIBILITY_EXPORTS = [
    "audio_transcript_diarization_disabled",
    "editor_speaker_preview_episode",
    "public_speaker_labels_for_episode",
    "public_speaker_labels_for_transcript",
    "strict_public_speaker_labels_for_transcript",
    "public_speaker_labels_for_audio",
    "strict_public_speaker_labels_for_audio",
    "public_episode_from_request",
    "public_one_off_speaker_labels_for_transcript",
    "public_speaker_mapping_for_transcript",
    "apply_public_speaker_mapping_to_podlove_data",
    "apply_public_speaker_mapping_to_dote_data",
    "apply_public_speaker_mapping_to_webvtt_content",
]


@pytest.mark.parametrize(
    "module,name",
    [(module, name) for module, names in FORMAT_EXPORTS.items() for name in names]
    + [("visibility", name) for name in VISIBILITY_EXPORTS],
)
def test_historical_import_is_the_domain_callable(module, name):
    domain = importlib.import_module(f"cast.transcripts.{module}")
    assert getattr(legacy, name) is getattr(domain, name)
    assert getattr(legacy, name).__module__ == domain.__name__


def test_compatibility_module_contains_no_policy_or_transform_definitions():
    tree = ast.parse(Path(legacy.__file__).read_text())
    assert not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) for node in ast.walk(tree))


def test_format_transforms_import_without_django_settings():
    code = """
import sys
import cast  # The package bootstrap imports django.apps; formats must add no Django imports.
bootstrap_modules = set(sys.modules)
from cast.transcripts import dote, podlove, webvtt
assert not any(name == 'django' or name.startswith('django.') for name in set(sys.modules) - bootstrap_modules)
assert not any(name == 'cast.models' or name.startswith('cast.models.') for name in sys.modules)
assert podlove.sanitize_podlove_data({'transcripts': [{'speaker': 'Hidden', 'text': 'hi'}]}, set()) == {'transcripts': [{'text': 'hi'}]}
assert dote.sanitize_dote_data({'lines': [{'speakerDesignation': 'Hidden'}]}, set()) == {'lines': [{'speakerDesignation': ''}]}
assert webvtt.sanitize_webvtt_content('WEBVTT\\n\\n00:00.000 --> 00:01.000\\n<v Hidden>hi</v>\\n', set()).endswith('\\nhi\\n')
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
