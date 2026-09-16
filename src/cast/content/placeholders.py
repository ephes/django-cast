"""Preserve stored blocks that the author format cannot edit."""

from __future__ import annotations

from typing import Any

from .blocks import ConversionContext
from .errors import ErrorCollector


def placeholder_for(index: int, block: dict, prefix: str) -> dict:
    """Return an author-facing placeholder for one stored block."""
    return {
        "type": "unsupported",
        "value": {"stored_type": block.get("type"), "position": f"{prefix}.{index}"},
    }


def resolve_placeholder(
    value: Any,
    *,
    ctx: ConversionContext,
    path: str,
    errors: ErrorCollector,
) -> tuple[dict | None, int | None]:
    """Resolve an author placeholder against its exact stored position and type."""
    existing_section = ctx.existing_section
    if existing_section is None:
        errors.add(f"{path}.type", "unsupported_block_type", "Block type 'unsupported' is not supported.")
        return None, None
    if not isinstance(value, dict):
        errors.add(f"{path}.value", "invalid", "Expected an object value.")
        return None, None
    stored_type = value.get("stored_type")
    position = value.get("position")
    if not isinstance(stored_type, str) or not isinstance(position, str):
        errors.add(
            f"{path}.value",
            "invalid",
            "Unsupported placeholders need stored_type and position.",
        )
        return None, None

    path_prefix = ctx.path_prefix
    assert path_prefix is not None
    prefix = f"{path_prefix}."
    try:
        existing_index = int(position.removeprefix(prefix))
    except ValueError:
        existing_index = -1
    if not position.startswith(prefix) or existing_index < 0 or existing_index >= len(existing_section):
        errors.add(
            f"{path}.value.position",
            "invalid",
            "Unsupported placeholder position does not match a stored block.",
        )
        return None, None
    existing_block = existing_section[existing_index]
    if existing_block.get("type") != stored_type:
        errors.add(
            f"{path}.value.stored_type",
            "invalid",
            "Unsupported placeholder does not match the stored block.",
        )
        return None, None
    return dict(existing_block), existing_index
