"""Transport-neutral conversion between author blocks and StreamField values."""

from __future__ import annotations

from typing import Any

from .blocks import UNSUPPORTED, ConversionContext, content_converters
from .errors import ContentValidationError, ErrorCollector
from .placeholders import placeholder_for, resolve_placeholder


def _path_prefix(ctx: ConversionContext) -> str:
    path_prefix = ctx.path_prefix
    if path_prefix is None:
        raise ValueError("path_prefix is required when section is None")
    return path_prefix


def author_blocks_to_section(blocks: Any, *, ctx: ConversionContext) -> list[dict]:
    """Convert author blocks, raising one transport-neutral validation error."""
    errors = ErrorCollector()
    result = convert_author_blocks(blocks, ctx=ctx, errors=errors)
    if errors:
        raise ContentValidationError(errors)
    return result


def convert_author_blocks(blocks: Any, *, ctx: ConversionContext, errors: ErrorCollector) -> list[dict]:
    """Convert author blocks into StreamField values while collecting input errors."""
    path_prefix = _path_prefix(ctx)
    if not isinstance(blocks, list):
        errors.add(path_prefix, "invalid", f"{path_prefix} must be a list of blocks.")
        return []

    result: list[dict] = []
    preserved_unsupported_indexes: set[int] = set()
    converters = content_converters(ctx.section)
    for index, block in enumerate(blocks):
        base = f"{path_prefix}.{index}"
        if not isinstance(block, dict) or "type" not in block:
            errors.add(f"{base}.type", "required", "Each block needs a 'type'.")
            continue
        block_type = block.get("type")
        value = block.get("value")
        if not isinstance(block_type, str):
            errors.add(f"{base}.type", "unsupported_block_type", f"Block type {block_type!r} is not supported.")
            continue

        if block_type == "unsupported":
            before = len(errors)
            preserved, existing_index = resolve_placeholder(value, ctx=ctx, path=base, errors=errors)
            if len(errors) > before or preserved is None:
                continue
            assert existing_index is not None
            if existing_index in preserved_unsupported_indexes:
                errors.add(
                    f"{base}.value.position", "duplicate", "Unsupported placeholder position is already preserved."
                )
                continue
            preserved_unsupported_indexes.add(existing_index)
            result.append(preserved)
            continue

        converter = converters.get(block_type)
        if converter is None:
            errors.add(f"{base}.type", "unsupported_block_type", f"Block type {block_type!r} is not supported.")
            continue
        before = len(errors)
        prepared = converter.to_stream(value, ctx=ctx, path=f"{base}.value", errors=errors)
        if len(errors) == before:
            result.append({"type": block_type, "value": prepared})
    return result


def section_to_author_blocks(section_value: list[dict], *, ctx: ConversionContext) -> list[dict]:
    """Convert stored StreamField values to the curated author format."""
    path_prefix = _path_prefix(ctx)
    author: list[dict] = []
    converters = content_converters(ctx.section)
    for index, block in enumerate(section_value):
        block_type = block.get("type")
        value = block.get("value")
        converter = converters.get(block_type) if isinstance(block_type, str) else None
        if converter is None:
            author.append(placeholder_for(index, block, path_prefix))
            continue
        author_value = converter.to_author(value, ctx=ctx)
        if author_value is UNSUPPORTED:
            author.append(placeholder_for(index, block, path_prefix))
        else:
            author.append({"type": block_type, "value": author_value})
    return author
