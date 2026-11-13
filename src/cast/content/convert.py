"""Transport-neutral conversion between author blocks and StreamField values."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, TypeGuard
from uuid import uuid4

from ..post_body_blocks import POST_BODY_SECTIONS
from .blocks import UNSUPPORTED, ConversionContext, content_converters
from .errors import ContentValidationError, ErrorCollector
from .media_refs import MediaResolution
from .placeholders import placeholder_for, resolve_placeholder


def content_section(path_prefix: str) -> str | None:
    """Return the configured Post body section named by a dotted path."""
    section = path_prefix.split(".", 1)[0]
    return section if section in POST_BODY_SECTIONS else None


def _path_prefix(ctx: ConversionContext) -> str:
    path_prefix = ctx.path_prefix
    if path_prefix is None:
        raise ValueError("path_prefix is required when section is None")
    return path_prefix


def _valid_block_identity(identity: Any) -> TypeGuard[str]:
    return isinstance(identity, str) and 0 < len(identity) <= 64


def _unique_block_identities(section_value: list[Any]) -> dict[str, int | None]:
    """Map each valid stored ID to its index, or ``None`` when the section repeats it."""
    identities: dict[str, int | None] = {}
    for index, stored in enumerate(section_value):
        identity = stored.get("id") if isinstance(stored, dict) else None
        if _valid_block_identity(identity):
            identities[identity] = None if identity in identities else index
    return identities


def _with_media_resolution(ctx: ConversionContext, blocks: list[Any], *, stored: bool) -> ConversionContext:
    resolution = ctx.media_resolution or MediaResolution(ctx.user)
    if resolution.user is not ctx.user:
        raise ValueError("Media resolution belongs to another user.")
    if not stored or ctx.user is not None:
        resolution.prefetch(blocks, stored=stored)
    return replace(ctx, media_resolution=resolution)


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

    ctx = _with_media_resolution(ctx, blocks, stored=False)
    result: list[dict] = []
    converters = content_converters(ctx.section)
    existing = ctx.existing_section or []
    existing_by_id = _unique_block_identities(existing)
    used_existing_indexes: set[int] = set()
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

        existing_index = None
        if "existing_block_id" in block:
            identity = block["existing_block_id"]
            existing_index = existing_by_id.get(identity) if isinstance(identity, str) else None
            if (
                existing_index is None
                or block_type == "unsupported"
                or existing[existing_index].get("type") != block_type
                or existing_index in used_existing_indexes
            ):
                errors.add(
                    f"{base}.existing_block_id",
                    "invalid",
                    "Block identity must name one existing block of the same type in this section and revision, used only once.",
                )
                continue
            used_existing_indexes.add(existing_index)

        if block_type == "unsupported":
            before = len(errors)
            preserved, existing_index = resolve_placeholder(value, ctx=ctx, path=base, errors=errors)
            if len(errors) > before or preserved is None:
                continue
            assert existing_index is not None
            if existing_index in used_existing_indexes:
                errors.add(
                    f"{base}.value.position", "duplicate", "Unsupported placeholder position is already preserved."
                )
                continue
            used_existing_indexes.add(existing_index)
            result.append(preserved)
            continue

        converter = converters.get(block_type)
        if converter is None:
            errors.add(f"{base}.type", "unsupported_block_type", f"Block type {block_type!r} is not supported.")
            continue
        before = len(errors)
        prepared = converter.to_stream(value, ctx=ctx, path=f"{base}.value", errors=errors)
        if len(errors) == before:
            converted = {
                "type": block_type,
                "value": prepared,
                "id": block["existing_block_id"] if existing_index is not None else str(uuid4()),
            }
            result.append(converted)
    return result


def section_to_author_blocks(section_value: list[dict], *, ctx: ConversionContext) -> list[dict]:
    """Convert stored StreamField values to the curated author format."""
    path_prefix = _path_prefix(ctx)
    ctx = _with_media_resolution(ctx, section_value, stored=True)
    author: list[dict] = []
    converters = content_converters(ctx.section)
    # Expose only identities the write side can bind back: a stored ID repeated in
    # the section is ambiguous, so its blocks round-trip as new blocks instead.
    unique_ids = _unique_block_identities(section_value)
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
            converted = {"type": block_type, "value": author_value}
            identity = block.get("id")
            if _valid_block_identity(identity) and unique_ids.get(identity) is not None:
                converted["existing_block_id"] = identity
            author.append(converted)
    return author
