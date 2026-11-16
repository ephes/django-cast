"""Unambiguous JSON admission shared by editor mutation endpoints."""

from typing import Any

from django.conf import settings
from rest_framework.exceptions import ParseError
from rest_framework.parsers import JSONParser
from rest_framework.utils import json

from .errors import EditorValidationError


def _unique_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EditorValidationError(
                {"non_field_errors": [{"code": "duplicate_member", "message": "JSON object members must be unique."}]}
            )
        result[key] = value
    return result


class EditorJSONParser(JSONParser):
    def parse(self, stream: Any, media_type: str | None = None, parser_context: dict[str, Any] | None = None) -> Any:
        encoding = (parser_context or {}).get("encoding", settings.DEFAULT_CHARSET)
        try:
            # bytes.decode admits text codecs only, matching DRF's charset contract.
            return json.loads(
                stream.read().decode(encoding),
                object_pairs_hook=_unique_members,
                parse_constant=json.strict_constant if self.strict else None,
            )
        except (ValueError, LookupError) as exc:
            raise ParseError("Invalid JSON request body or charset.") from exc
