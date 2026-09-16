from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from wagtail.blocks import Block

from ...content.blocks import (
    UNSUPPORTED,
    ConversionContext,
    GenericBlockConverter,
    _custom_author_value as _custom_author_value,
    _unwrap_list_item_values as _unwrap_list_item_values,
    content_converters,
)
from ...content.errors import ErrorCollector, flatten_django_validation_error
from ...content.media_refs import (
    audio_choosable_by,
    get_choosable_audio as get_choosable_audio,
    get_choosable_image as get_choosable_image,
    get_choosable_object as get_choosable_object,
    get_choosable_video as get_choosable_video,
    image_choosable_by,
    video_choosable_by,
)
from ...content.placeholders import placeholder_for, resolve_placeholder
from ...post_body_blocks import POST_BODY_SECTIONS
from .errors import EditorValidationError

SUPPORTED_BODY_BLOCKS = frozenset(name for name, converter in content_converters(None).items() if converter.editable)
SUPPORTED_OVERVIEW_BLOCKS = SUPPORTED_BODY_BLOCKS


def _content_section(path_prefix: str) -> str | None:
    section = path_prefix.split(".", 1)[0]
    if section not in POST_BODY_SECTIONS:
        return None
    return section


def _custom_block_map(section: str | None) -> dict[str, Block]:
    return {
        name: converter.block
        for name, converter in content_converters(section).items()
        if isinstance(converter, GenericBlockConverter)
    }


def _flatten_django_validation_error(exc: DjangoValidationError, path: str) -> dict[str, list[dict[str, str]]]:
    """Compatibility shim for private editor tests; remove with converter slice 7."""
    errors = ErrorCollector()
    errors.extend(flatten_django_validation_error(exc, path))
    return errors.error_map


def author_blocks_to_section(
    blocks: list[dict], *, user: Any, path_prefix: str, existing_section: list[dict] | None = None
) -> list[dict]:
    """Convert an author-facing block list into a Wagtail body-section StreamField value.

    ``user`` is required: referenced images are validated for both existence and the caller's Wagtail
    ``choose`` permission, so a client cannot attach images it could not select in the Wagtail admin.

    Raises :class:`EditorValidationError` aggregating every problem with a field-precise path.
    """
    errors = ErrorCollector()
    result: list[dict] = []
    preserved_unsupported_indexes: set[int] = set()
    section = _content_section(path_prefix)
    converters = content_converters(section)
    ctx = ConversionContext(section=section, user=user, existing_section=existing_section, path_prefix=path_prefix)

    if not isinstance(blocks, list):
        errors.add(path_prefix, "invalid", f"{path_prefix} must be a list of blocks.")
        raise EditorValidationError(errors.error_map)

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
            preserved, existing_index = resolve_placeholder(value, ctx=ctx, path=base, errors=errors)
            if preserved is None:
                continue
            assert existing_index is not None
            if existing_index in preserved_unsupported_indexes:
                errors.add(
                    f"{base}.value.position", "duplicate", "Unsupported placeholder position is already preserved."
                )
                continue
            preserved_unsupported_indexes.add(existing_index)
            assert preserved is not None
            result.append(preserved)
            continue

        converter = converters.get(block_type)
        if converter is not None:
            before = len(errors)
            prepared = converter.to_stream(value, ctx=ctx, path=f"{base}.value", errors=errors)
            if len(errors) == before:
                result.append({"type": block_type, "value": prepared})
            continue

        errors.add(f"{base}.type", "unsupported_block_type", f"Block type {block_type!r} is not supported.")

    if errors:
        raise EditorValidationError(errors.error_map)
    return result


def author_blocks_to_overview(
    blocks: list[dict], *, user: Any, path_prefix: str = "overview", existing_section: list[dict] | None = None
) -> list[dict]:
    """Backward-compatible wrapper for overview conversion."""
    return author_blocks_to_section(blocks, user=user, path_prefix=path_prefix, existing_section=existing_section)


def _media_ref_is_available(block_type: str, value: Any, user: Any) -> bool:
    """Compatibility helper retained for private tests until converter slice 7."""
    if block_type == "image":
        return image_choosable_by(value, user)
    if block_type == "audio":
        return audio_choosable_by(value, user)
    if block_type == "video":
        return video_choosable_by(value, user)
    raise ValueError(f"Unsupported media block type: {block_type}")


def section_to_author_blocks(
    section_value: list[dict], *, path_prefix: str = "overview", user: Any | None = None
) -> list[dict]:
    """Inverse of :func:`author_blocks_to_section` for supported block types."""
    author: list[dict] = []
    section = _content_section(path_prefix)
    converters = content_converters(section)
    ctx = ConversionContext(section=section, user=user, path_prefix=path_prefix)
    for index, block in enumerate(section_value):
        block_type = block.get("type")
        value = block.get("value")
        converter = converters.get(block_type) if isinstance(block_type, str) else None
        if converter is not None:
            author_value = converter.to_author(value, ctx=ctx)
            if author_value is UNSUPPORTED:
                author.append(placeholder_for(index, block, path_prefix))
            else:
                author.append({"type": block_type, "value": author_value})
        else:
            author.append(placeholder_for(index, block, path_prefix))
    return author


def overview_to_author_blocks(overview_value: list[dict]) -> list[dict]:
    """Backward-compatible wrapper for overview serialization."""
    return section_to_author_blocks(overview_value, path_prefix="overview")
