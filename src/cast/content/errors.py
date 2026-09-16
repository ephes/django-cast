"""Transport-neutral content validation errors."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from django.core.exceptions import ValidationError as DjangoValidationError


@dataclass(frozen=True)
class ContentError:
    """One field-precise content validation error."""

    path: str
    code: str
    message: str


class ErrorCollector:
    """Accumulate content errors while preserving insertion order."""

    def __init__(self) -> None:
        self._errors: list[ContentError] = []

    def add(self, path: str, code: str, message: str) -> None:
        self._errors.append(ContentError(path=path, code=code, message=message))

    def extend(self, errors: Iterable[ContentError]) -> None:
        self._errors.extend(errors)

    def __bool__(self) -> bool:
        return bool(self._errors)

    def __len__(self) -> int:
        return len(self._errors)

    @property
    def error_map(self) -> dict[str, list[dict[str, str]]]:
        result: dict[str, list[dict[str, str]]] = {}
        for error in self._errors:
            result.setdefault(error.path, []).append({"code": error.code, "message": error.message})
        return result


class ContentValidationError(Exception):
    """Raised when transport-neutral content conversion fails."""

    def __init__(self, errors: ErrorCollector) -> None:
        self.errors = errors
        super().__init__("Content validation failed.")

    @property
    def error_map(self) -> dict[str, list[dict[str, str]]]:
        return self.errors.error_map


def _error_items(exc: DjangoValidationError, path: str) -> list[ContentError]:
    messages = getattr(exc, "messages", None) or [str(exc)]
    code = getattr(exc, "code", None) or "invalid"
    return [ContentError(path=path, code=str(code), message=str(message)) for message in messages]


def flatten_django_validation_error(exc: DjangoValidationError, path: str) -> list[ContentError]:
    """Flatten a Django or Wagtail validation error tree into dotted paths."""
    flat: list[ContentError] = []
    block_errors = getattr(exc, "block_errors", None)
    if isinstance(block_errors, dict):
        for key, child in block_errors.items():
            if isinstance(child, DjangoValidationError):
                flat.extend(flatten_django_validation_error(child, f"{path}.{key}"))

    non_block_errors = getattr(exc, "non_block_errors", None)
    if isinstance(non_block_errors, list):
        for child in non_block_errors:
            if isinstance(child, DjangoValidationError):
                flat.extend(flatten_django_validation_error(child, path))

    error_dict = getattr(exc, "error_dict", None)
    if isinstance(error_dict, dict):
        for key, children in error_dict.items():
            for child in children:
                if isinstance(child, DjangoValidationError):
                    flat.extend(flatten_django_validation_error(child, f"{path}.{key}"))

    return flat or _error_items(exc, path)
