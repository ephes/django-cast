from __future__ import annotations

from typing import Any

from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


class EditorValidationError(APIException):
    """Field-precise validation failure rendered as the editor validation envelope."""

    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, error_map: dict[str, list[dict[str, str]]]) -> None:
        self.error_map = error_map
        super().__init__(detail="validation_error")


class EditorPermissionDenied(APIException):
    """Authorization failure against a Wagtail page permission."""

    status_code = status.HTTP_403_FORBIDDEN

    def __init__(self, detail: str, *, parent_id: int | None = None) -> None:
        self.detail_text = detail
        self.parent_id = parent_id
        super().__init__(detail=detail)


def _flatten_drf_errors(detail: Any, prefix: str = "") -> dict[str, list[dict[str, str]]]:
    """Flatten a DRF ValidationError detail into {dotted.path: [{code, message}]}."""
    flat: dict[str, list[dict[str, str]]] = {}
    if isinstance(detail, dict):
        for key, value in detail.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            for sub_path, items in _flatten_drf_errors(value, path).items():
                flat.setdefault(sub_path, []).extend(items)
    elif isinstance(detail, list):
        leaves = [d for d in detail if not isinstance(d, (dict, list))]
        nested = [d for d in detail if isinstance(d, (dict, list))]
        if leaves:
            leaf_key = prefix if prefix else "non_field_errors"
            flat.setdefault(leaf_key, []).extend(
                {"code": getattr(d, "code", "invalid"), "message": str(d)} for d in leaves
            )
        for index, item in enumerate(nested):
            child_path = f"{prefix}.{index}" if prefix else str(index)
            for sub_path, items in _flatten_drf_errors(item, child_path).items():
                flat.setdefault(sub_path, []).extend(items)
    else:
        flat.setdefault(prefix, []).append({"code": getattr(detail, "code", "invalid"), "message": str(detail)})
    return flat


def editor_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    if isinstance(exc, EditorValidationError):
        return Response(
            {"code": "validation_error", "errors": exc.error_map},
            status=exc.status_code,
        )
    if isinstance(exc, EditorPermissionDenied):
        return Response(
            {"code": "permission_denied", "detail": exc.detail_text, "parent_id": exc.parent_id},
            status=exc.status_code,
        )
    if isinstance(exc, DRFValidationError):
        return Response(
            {"code": "validation_error", "errors": _flatten_drf_errors(exc.detail)},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return drf_exception_handler(exc, context)
