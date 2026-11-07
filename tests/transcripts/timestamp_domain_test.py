"""Malformed stored JSON times must stay read-only and recoverable in editorial paths."""

import json
import sys
from decimal import Decimal

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse

from cast.devdata import create_transcript
from cast.models import Transcript
from cast.transcripts import parsing


@pytest.mark.parametrize(
    "value",
    [
        float("inf"),
        -float("inf"),
        float("nan"),
        "Infinity",
        "NaN",
        "1e400",
        10**400,
        "9" * 400 + ":00:00",
        "00:Infinity",
        "00:NaN",
    ],
)
def test_timestamp_parsing_and_formatting_refuse_nonfinite_or_unrepresentable_values(value):
    assert parsing.parse_timestamp_seconds(value) is None
    assert parsing.parse_timestamp_decimal_seconds(value) is None
    assert parsing.format_sample_timestamp(parsing.parse_timestamp_seconds(value)) == ""


@pytest.mark.parametrize("value", [Decimal("Infinity"), Decimal("NaN"), Decimal("1e400")])
def test_decimal_formatter_refuses_unusable_timestamps(value):
    assert parsing.format_decimal_timestamp(value) == ""


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field,value",
    [
        ("start", "Infinity"),
        ("start", float("inf")),
        ("start", 10**400),
        ("start_ms", float("inf")),
        ("start_ms", 10**400),
        ("start", float("nan")),
    ],
)
def test_editor_samples_and_voice_candidates_handle_invalid_timing_without_writes(admin_client, audio, field, value):
    transcript = create_transcript(audio=audio)
    data = {
        "transcripts": [
            {
                "speaker": "Synthetic",
                "text": "A sufficiently useful synthetic transcript sample for editorial review.",
                "end": 30,
                field: value,
            }
        ]
    }
    content = json.dumps(data).encode()
    if isinstance(value, float) and value == float("inf"):
        content = content.replace(b"Infinity", b"1e400")
    transcript.podlove.save("synthetic-times.json", ContentFile(content), save=False)
    Transcript.objects.filter(pk=transcript.pk).update(podlove=transcript.podlove.name)
    transcript.refresh_from_db()
    samples = transcript.get_speaker_samples()
    assert samples["Synthetic"][0].start_seconds is None
    assert transcript.get_voice_reference_candidates() == []
    response = admin_client.get(reverse("cast-transcript:edit", args=[transcript.pk]))
    assert response.status_code == 200
    assert transcript._read_file_bytes("podlove") == content


@pytest.mark.django_db
def test_valid_fractional_editor_times_keep_samples_and_voice_candidates(audio):
    transcript = create_transcript(
        audio=audio,
        podlove={
            "transcripts": [
                {
                    "speaker": "Synthetic",
                    "start": "00:00:00.125",
                    "end": "00:00:30.875",
                    "text": "A sufficiently useful synthetic transcript sample for editorial review.",
                }
            ]
        },
    )
    assert transcript.get_speaker_samples()["Synthetic"][0].start_seconds == 0.125
    candidates = transcript.get_voice_reference_candidates()
    assert candidates and candidates[0].start_seconds == Decimal("0.125")


def test_decimal_parsers_refuse_integers_beyond_string_conversion_limit():
    value = 10**5000
    previous = sys.get_int_max_str_digits()
    try:
        sys.set_int_max_str_digits(4300)
        assert parsing.parse_timestamp_decimal_seconds(value) is None
        assert (
            parsing.parse_record_decimal_seconds(
                {"start_ms": value}, millisecond_field="start_ms", timestamp_fields=("start",)
            )
            is None
        )
    finally:
        sys.set_int_max_str_digits(previous)
