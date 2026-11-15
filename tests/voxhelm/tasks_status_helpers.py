"""Shared test data and setup helpers."""

VALID_PODLOVE_ARTIFACT = b'{"transcripts": [{"text": "done"}]}'


VALID_DOTE_ARTIFACT = (
    b'{"lines": [{"startTime": "00:00:00,000", "endTime": "00:00:00,100", "speakerDesignation": "", "text": "done"}]}'
)


VALID_VTT_ARTIFACT = b"WEBVTT\n\n00:00:00.000 --> 00:00:00.100\ndone\n"
