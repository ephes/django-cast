from __future__ import annotations

from typing import Any

from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.exceptions import NotFound as DRFNotFound
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


class EditorNotFound(APIException):
    """Resource lookup failure rendered as an editor error envelope."""

    status_code = status.HTTP_404_NOT_FOUND

    def __init__(self, detail: str) -> None:
        self.detail_text = detail
        super().__init__(detail=detail)


class EditorFlatError(APIException):
    """Whole-request editor failure rendered as ``{"code": ..., "detail": ...}``."""

    def __init__(self, code: str, detail: str, *, status_code: int) -> None:
        self.code_text = code
        self.detail_text = detail
        self.status_code = status_code
        super().__init__(detail=detail)


class EditorRevisionConflict(APIException):
    """Revision token mismatch for draft updates."""

    status_code = status.HTTP_409_CONFLICT

    def __init__(self, *, current_revision_id: int | None, submitted_base_revision_id: int, edit_url: str) -> None:
        self.current_revision_id = current_revision_id
        self.submitted_base_revision_id = submitted_base_revision_id
        self.edit_url = edit_url
        super().__init__(detail="revision_conflict")


def _flatten_drf_errors(detail: Any, prefix: str = "") -> dict[str, list[dict[str, str]]]:
    """Flatten a DRF ValidationError detail into {dotted.path: [{code, message}]}."""
    flat: dict[str, list[dict[str, str]]] = {}
    if isinstance(detail, dict):
        for key, value in detail.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            for sub_path, items in _flatten_drf_errors(value, path).items():
                flat.setdefault(sub_path, []).extend(items)
    elif isinstance(detail, list):
        leaf_key = prefix if prefix else "non_field_errors"
        for index, item in enumerate(detail):
            if isinstance(item, (dict, list)):
                child_path = f"{prefix}.{index}" if prefix else str(index)
                for sub_path, items in _flatten_drf_errors(item, child_path).items():
                    flat.setdefault(sub_path, []).extend(items)
            else:
                flat.setdefault(leaf_key, []).append({"code": getattr(item, "code", "invalid"), "message": str(item)})
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
        data: dict[str, Any] = {"code": "permission_denied", "detail": exc.detail_text}
        if exc.parent_id is not None:
            data["parent_id"] = exc.parent_id
        return Response(data, status=exc.status_code)
    if isinstance(exc, EditorNotFound):
        return Response(
            {"code": "not_found", "detail": exc.detail_text},
            status=exc.status_code,
        )
    if isinstance(exc, EditorFlatError):
        return Response({"code": exc.code_text, "detail": exc.detail_text}, status=exc.status_code)
    if isinstance(exc, DRFNotFound):
        return Response({"code": "not_found", "detail": str(exc.detail)}, status=status.HTTP_404_NOT_FOUND)
    if isinstance(exc, EditorRevisionConflict):
        return Response(
            {
                "code": "revision_conflict",
                "detail": "The page has a newer revision than the submitted base revision.",
                "current_revision_id": exc.current_revision_id,
                "submitted_base_revision_id": exc.submitted_base_revision_id,
                "edit_url": exc.edit_url,
            },
            status=exc.status_code,
        )
    if isinstance(exc, DRFValidationError):
        return Response(
            {"code": "validation_error", "errors": _flatten_drf_errors(exc.detail)},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return drf_exception_handler(exc, context)
