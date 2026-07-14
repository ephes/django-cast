"""Pure transcript parsing and formatting helpers."""

import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

VOICE_REFERENCE_CANDIDATE_QUANTUM = Decimal("0.001")
LOW_SIGNAL_TRANSCRIPT_SAMPLE_TEXTS = frozenset(
    {
        "ah",
        "ahm",
        "aeh",
        "aehm",
        "genau",
        "hm",
        "hmm",
        "ja",
        "mhm",
        "no",
        "ok",
        "okay",
        "stimmt",
        "yes",
    }
)


def segment_sort_key(segment: dict) -> float:
    try:
        return float(segment.get("start") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def quantize_seconds(value: Decimal) -> Decimal:
    return value.quantize(VOICE_REFERENCE_CANDIDATE_QUANTUM, rounding=ROUND_HALF_UP)


def format_decimal_timestamp(value: Decimal) -> str:
    total_milliseconds = int((value * 1000).to_integral_value(rounding=ROUND_HALF_UP))
    total_seconds, milliseconds = divmod(total_milliseconds, 1000)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
    return f"{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def clean_sample_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()


def clean_speaker_label(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def sample_text_is_useful(text: str, *, min_chars: int, min_words: int) -> bool:
    if len(text) < min_chars:
        return False
    words = re.findall(r"\w+", text)
    if len(words) < min_words:
        return False
    # The low-signal list is intentionally Latin-script only; non-Latin text falls through as useful.
    normalized_text = normalize_sample_text(text)
    if normalized_text in LOW_SIGNAL_TRANSCRIPT_SAMPLE_TEXTS:
        return False
    normalized_words = normalized_text.split()
    return not normalized_words or not all(word in LOW_SIGNAL_TRANSCRIPT_SAMPLE_TEXTS for word in normalized_words)


def normalize_sample_text(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text.casefold()).encode("ascii", errors="ignore").decode("ascii")
    normalized_text = re.sub(r"[^a-z0-9]+", " ", ascii_text)
    return re.sub(r"\s+", " ", normalized_text).strip()


def truncate_sample_text(text: str, *, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars].rsplit(" ", 1)[0] or text[:max_chars]
    return f"{truncated}..."


def parse_record_start_seconds(record: dict[str, Any], *, timestamp_fields: tuple[str, ...]) -> float | None:
    start_ms = record.get("start_ms")
    if not isinstance(start_ms, bool) and isinstance(start_ms, int | float) and start_ms >= 0:
        return float(start_ms) / 1000
    for field_name in timestamp_fields:
        start_seconds = parse_timestamp_seconds(record.get(field_name))
        if start_seconds is not None:
            return start_seconds
    return None


def parse_record_decimal_seconds(
    record: dict[str, Any],
    *,
    millisecond_field: str,
    timestamp_fields: tuple[str, ...],
) -> Decimal | None:
    milliseconds = record.get(millisecond_field)
    if not isinstance(milliseconds, bool) and isinstance(milliseconds, int | float) and milliseconds >= 0:
        return quantize_seconds(Decimal(str(milliseconds)) / Decimal("1000"))
    for field_name in timestamp_fields:
        seconds = parse_timestamp_decimal_seconds(record.get(field_name))
        if seconds is not None:
            return seconds
    return None


def parse_timestamp_decimal_seconds(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return quantize_seconds(Decimal(str(value))) if value >= 0 else None
    if not isinstance(value, str):
        return None
    timestamp = value.strip().replace(",", ".")
    if not timestamp:
        return None
    parts = timestamp.split(":")
    try:
        if len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = Decimal(parts[2])
        elif len(parts) == 2:
            hours = 0
            minutes = int(parts[0])
            seconds = Decimal(parts[1])
        elif len(parts) == 1:
            seconds = Decimal(timestamp)
            return quantize_seconds(seconds) if seconds >= 0 else None
        else:
            return None
    except (ValueError, ArithmeticError):
        return None
    total_seconds = (Decimal(hours) * Decimal("3600")) + (Decimal(minutes) * Decimal("60")) + seconds
    return quantize_seconds(total_seconds) if total_seconds >= 0 else None


def parse_timestamp_seconds(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value) if value >= 0 else None
    if not isinstance(value, str):
        return None
    timestamp = value.strip().replace(",", ".")
    if not timestamp:
        return None
    parts = timestamp.split(":")
    try:
        if len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])
        elif len(parts) == 2:
            hours = 0
            minutes = int(parts[0])
            seconds = float(parts[1])
        elif len(parts) == 1:
            return float(timestamp) if float(timestamp) >= 0 else None
        else:
            return None
    except ValueError:
        return None
    start_seconds = (hours * 3600) + (minutes * 60) + seconds
    return start_seconds if start_seconds >= 0 else None


def format_sample_timestamp(start_seconds: float | None) -> str:
    if start_seconds is None:
        return ""
    total_seconds = int(start_seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"
