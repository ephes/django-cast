"""Shared test data and setup helpers."""

from decimal import Decimal


def podlove_segment(
    speaker: str,
    start: str,
    end: str,
    *,
    text: str | None = None,
    voice: str | None = None,
) -> dict:
    return {
        "speaker": speaker,
        "voice": speaker if voice is None else voice,
        "start_ms": int(Decimal(start) * 1000),
        "end_ms": int(Decimal(end) * 1000),
        "text": text if text is not None else f"{speaker} says enough useful words for a candidate range.",
    }
