import pytest

from cast.devdata import create_transcript
from cast.models.transcript import Transcript
from cast.transcripts.dote import convert_dote_to_podcastindex_transcript, time_to_seconds


@pytest.mark.django_db
def test_transcript_podlove_data_no_podlove_or_dote():
    transcript = Transcript()
    assert transcript.podlove_data == {}
    assert transcript.dote_data == {}
    assert transcript.podcastindex_data == {}


@pytest.mark.django_db
def test_transcript_get_all_paths_skips_empty_fields():
    transcript = Transcript()
    assert transcript.get_all_paths() == set()


@pytest.mark.django_db
def test_transcript_data_missing_files(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    transcript = Transcript()
    transcript.podlove.name = "cast_transcript/missing.json"
    transcript.dote.name = "cast_transcript/missing_dote.json"
    assert transcript.podlove_data == {}
    assert transcript.dote_data == {}
    assert transcript.transcript_artifact_fingerprint() == ""


@pytest.fixture
def dote():
    return {
        "lines": [
            {
                "startTime": "00:00:00,000",
                "endTime": "00:00:01,000",
                "speakerDesignation": "speaker",
                "text": "text",
            }
        ]
    }


@pytest.mark.django_db
def test_transcript_dote_data(dote):
    transcript = create_transcript(dote=dote)
    assert transcript.dote_data == dote


@pytest.mark.django_db
def test_transcript_podcastindex_data(dote):
    transcript = create_transcript(dote=dote)
    assert transcript.podcastindex_data == {
        "version": "1.0",
        "segments": [
            {
                "startTime": 0.0,
                "endTime": 1.0,
                "speaker": "speaker",
                "body": "text",
            }
        ],
    }


def test_convert_dote_to_podcastindex_transcript(dote):
    podcastindex = convert_dote_to_podcastindex_transcript(dote)
    assert podcastindex == {
        "version": "1.0",
        "segments": [
            {
                "startTime": 0.0,
                "endTime": 1.0,
                "speaker": "speaker",
                "body": "text",
            }
        ],
    }


@pytest.mark.parametrize(
    "time_str, expected",
    [
        ("00:00:00,000", 0.0),
        ("00:00:01,000", 1.0),
        ("00:01:00,000", 60.0),
        ("01:00:00,000", 3600.0),
        ("01:00:00,500", 3600.5),
        ("00:00:01.500", 1.5),
        ("00:00:01,5", 1.5),
        ("00:00:01.5", 1.5),
        ("00:00:01,05", 1.05),
        ("00:00:01,050", 1.05),
        ("25:00:03,000", 90003.0),
        ("999:59:59,999", 3599999.999),
        (" 00:00:01,250 ", 1.25),
    ],
)
def test_time_to_seconds(time_str, expected):
    assert time_to_seconds(time_str) == expected


@pytest.mark.parametrize(
    "time_str",
    [
        "foobar",
        "",
        "00:00:01",
        "00:00:01,",
        "00:00:01,5000",
        "00:00:01;500",
        "00:00:01,500 trailing",
        "0:0:1,500",
        "00:60:00,000",
        "00:00:60,000",
        "1000:00:00,000",
        "9" * 4301 + ":00:00,000",
        None,
        1.5,
    ],
)
def test_time_to_seconds_invalid(time_str):
    with pytest.raises(ValueError):
        time_to_seconds(time_str)
