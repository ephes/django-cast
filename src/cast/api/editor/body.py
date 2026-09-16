from __future__ import annotations

import uuid
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
from ...post_body_blocks import POST_BODY_SECTIONS
from .errors import EditorValidationError

SUPPORTED_BODY_BLOCKS = frozenset({"paragraph", "code", "image", "gallery", "audio", "video"})
SUPPORTED_OVERVIEW_BLOCKS = SUPPORTED_BODY_BLOCKS


def _preserved_unsupported_block(
    value: Any, *, existing_section: list[dict] | None, base: str, path_prefix: str
) -> tuple[dict | None, int | None, dict[str, list[dict[str, str]]]]:
    if existing_section is None:
        return (
            None,
            None,
            {
                f"{base}.type": [
                    {"code": "unsupported_block_type", "message": "Block type 'unsupported' is not supported."}
                ]
            },
        )
    if not isinstance(value, dict):
        return None, None, {f"{base}.value": [{"code": "invalid", "message": "Expected an object value."}]}
    stored_type = value.get("stored_type")
    position = value.get("position")
    if not isinstance(stored_type, str) or not isinstance(position, str):
        return (
            None,
            None,
            {
                f"{base}.value": [
                    {"code": "invalid", "message": "Unsupported placeholders need stored_type and position."}
                ]
            },
        )
    prefix = f"{path_prefix}."
    try:
        existing_index = int(position.removeprefix(prefix))
    except ValueError:
        existing_index = -1
    if not position.startswith(prefix) or existing_index < 0 or existing_index >= len(existing_section):
        return (
            None,
            None,
            {
                f"{base}.value.position": [
                    {"code": "invalid", "message": "Unsupported placeholder position does not match a stored block."}
                ]
            },
        )
    existing_block = existing_section[existing_index]
    if existing_block.get("type") != stored_type:
        return (
            None,
            None,
            {
                f"{base}.value.stored_type": [
                    {"code": "invalid", "message": "Unsupported placeholder does not match the stored block."}
                ]
            },
        )
    return dict(existing_block), existing_index, {}


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


def _extend_error_map(errors: ErrorCollector, error_map: dict[str, list[dict[str, str]]]) -> None:
    for path, items in error_map.items():
        for item in items:
            errors.add(path, item["code"], item["message"])


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
            preserved, existing_index, placeholder_errors = _preserved_unsupported_block(
                value, existing_section=existing_section, base=base, path_prefix=path_prefix
            )
            if placeholder_errors:
                _extend_error_map(errors, placeholder_errors)
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

        if block_type not in SUPPORTED_BODY_BLOCKS:
            errors.add(f"{base}.type", "unsupported_block_type", f"Block type {block_type!r} is not supported.")
            continue

        if block_type == "code":
            if not isinstance(value, dict):
                errors.add(f"{base}.value", "invalid", "Expected an object value.")
                continue
            block_errors = False
            for key in ("language", "source"):
                if not isinstance(value.get(key), str) or not value.get(key):
                    errors.add(f"{base}.value.{key}", "required", f"Code block '{key}' is required.")
                    block_errors = True
            if block_errors:
                continue
            result.append({"type": "code", "value": {"language": value["language"], "source": value["source"]}})

        elif block_type == "image":
            image_id = value.get("id") if isinstance(value, dict) else None
            if not image_choosable_by(image_id, user):
                errors.add(
                    f"{base}.value.id",
                    "not_found",
                    f"Image {image_id} does not exist or is not accessible.",
                )
                continue
            result.append({"type": "image", "value": image_id})

        elif block_type == "gallery":
            if not isinstance(value, list) or not value:
                errors.add(f"{base}.value", "invalid", "Gallery value must be a non-empty list of image refs.")
                continue
            items = []
            gallery_ok = True
            for img_index, ref in enumerate(value):
                image_id = ref.get("id") if isinstance(ref, dict) else None
                if not image_choosable_by(image_id, user):
                    errors.add(
                        f"{base}.value.{img_index}.id",
                        "not_found",
                        f"Image {image_id} does not exist or is not accessible.",
                    )
                    gallery_ok = False
                    continue
                items.append({"id": str(uuid.uuid4()), "type": "item", "value": image_id})
            if not gallery_ok:
                continue
            result.append({"type": "gallery", "value": {"layout": "default", "gallery": items}})

        elif block_type == "audio":
            audio_id = value.get("id") if isinstance(value, dict) else None
            if not audio_choosable_by(audio_id, user):
                errors.add(f"{base}.value.id", "not_found", "Referenced media is not available.")
                continue
            result.append({"type": "audio", "value": audio_id})

        else:  # block_type == "video"
            video_id = value.get("id") if isinstance(value, dict) else None
            if not video_choosable_by(video_id, user):
                errors.add(f"{base}.value.id", "not_found", "Referenced media is not available.")
                continue
            result.append({"type": "video", "value": video_id})

    if errors:
        raise EditorValidationError(errors.error_map)
    return result


def author_blocks_to_overview(
    blocks: list[dict], *, user: Any, path_prefix: str = "overview", existing_section: list[dict] | None = None
) -> list[dict]:
    """Backward-compatible wrapper for overview conversion."""
    return author_blocks_to_section(blocks, user=user, path_prefix=path_prefix, existing_section=existing_section)


def _unsupported_placeholder(block_type: Any, *, path_prefix: str, index: int) -> dict:
    return {"type": "unsupported", "value": {"stored_type": block_type, "position": f"{path_prefix}.{index}"}}


def _media_ref_is_available(block_type: str, value: Any, user: Any) -> bool:
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
                author.append(_unsupported_placeholder(block_type, path_prefix=path_prefix, index=index))
            else:
                author.append({"type": block_type, "value": author_value})
        elif block_type == "code":
            if (
                isinstance(value, dict)
                and isinstance(value.get("language"), str)
                and isinstance(value.get("source"), str)
            ):
                author.append({"type": "code", "value": {"language": value["language"], "source": value["source"]}})
            else:
                author.append(_unsupported_placeholder(block_type, path_prefix=path_prefix, index=index))
        elif block_type in ("image", "audio", "video"):
            if user is not None and not _media_ref_is_available(block_type, value, user):
                author.append(_unsupported_placeholder(block_type, path_prefix=path_prefix, index=index))
            else:
                author.append({"type": block_type, "value": {"id": value}})
        elif block_type == "gallery":
            items = value.get("gallery", []) if isinstance(value, dict) else []
            if (
                isinstance(items, list)
                and len(items) > 0
                and all(isinstance(item, dict) and "value" in item for item in items)
                and (
                    user is None
                    or all(image_choosable_by(item["value"], user) for item in items if isinstance(item, dict))
                )
            ):
                author.append({"type": "gallery", "value": [{"id": item["value"]} for item in items]})
            else:
                author.append(_unsupported_placeholder(block_type, path_prefix=path_prefix, index=index))
        else:
            author.append(_unsupported_placeholder(block_type, path_prefix=path_prefix, index=index))
    return author


def overview_to_author_blocks(overview_value: list[dict]) -> list[dict]:
    """Backward-compatible wrapper for overview serialization."""
    return section_to_author_blocks(overview_value, path_prefix="overview")
