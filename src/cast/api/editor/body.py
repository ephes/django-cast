from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError

from ...content import blocks as content_blocks, media_refs
from ...content.blocks import ConversionContext
from ...content.convert import (
    author_blocks_to_section as convert_author_blocks_to_section,
    section_to_author_blocks as convert_section_to_author_blocks,
)
from ...content.errors import ContentValidationError, ErrorCollector, flatten_django_validation_error
from ...post_body_blocks import POST_BODY_SECTIONS
from .errors import EditorValidationError

SUPPORTED_BODY_BLOCKS = content_blocks.SUPPORTED_BODY_BLOCKS
SUPPORTED_OVERVIEW_BLOCKS = SUPPORTED_BODY_BLOCKS
_custom_author_value = content_blocks._custom_author_value
_custom_block_map = content_blocks._custom_block_map
_unwrap_list_item_values = content_blocks._unwrap_list_item_values
_media_ref_is_available = media_refs._media_ref_is_available
get_choosable_audio = media_refs.get_choosable_audio
get_choosable_image = media_refs.get_choosable_image
get_choosable_object = media_refs.get_choosable_object
get_choosable_video = media_refs.get_choosable_video


def _content_section(path_prefix: str) -> str | None:
    section = path_prefix.split(".", 1)[0]
    if section not in POST_BODY_SECTIONS:
        return None
    return section


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
    section = _content_section(path_prefix)
    ctx = ConversionContext(section=section, user=user, existing_section=existing_section, path_prefix=path_prefix)
    try:
        return convert_author_blocks_to_section(blocks, ctx=ctx)
    except ContentValidationError as exc:
        raise EditorValidationError(exc.error_map) from exc


def author_blocks_to_overview(
    blocks: list[dict], *, user: Any, path_prefix: str = "overview", existing_section: list[dict] | None = None
) -> list[dict]:
    """Backward-compatible wrapper for overview conversion."""
    return author_blocks_to_section(blocks, user=user, path_prefix=path_prefix, existing_section=existing_section)


def section_to_author_blocks(
    section_value: list[dict], *, path_prefix: str = "overview", user: Any | None = None
) -> list[dict]:
    """Inverse of :func:`author_blocks_to_section` for supported block types."""
    section = _content_section(path_prefix)
    ctx = ConversionContext(section=section, user=user, path_prefix=path_prefix)
    return convert_section_to_author_blocks(section_value, ctx=ctx)


def overview_to_author_blocks(overview_value: list[dict]) -> list[dict]:
    """Backward-compatible wrapper for overview serialization."""
    return section_to_author_blocks(overview_value, path_prefix="overview")
