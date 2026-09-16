from __future__ import annotations

from typing import Any

from ...content.blocks import ConversionContext
from ...content.convert import (
    author_blocks_to_section as convert_author_blocks_to_section,
    content_section,
    section_to_author_blocks as convert_section_to_author_blocks,
)
from ...content.errors import ContentValidationError
from ...content.media_refs import (
    get_choosable_audio as get_choosable_audio,
    get_choosable_image as get_choosable_image,
)
from .errors import EditorValidationError


def author_blocks_to_section(
    blocks: list[dict], *, user: Any, path_prefix: str, existing_section: list[dict] | None = None
) -> list[dict]:
    """Convert an author-facing block list into a Wagtail body-section StreamField value.

    ``user`` is required: referenced images are validated for both existence and the caller's Wagtail
    ``choose`` permission, so a client cannot attach images it could not select in the Wagtail admin.

    Raises :class:`EditorValidationError` aggregating every problem with a field-precise path.
    """
    section = content_section(path_prefix)
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
    section = content_section(path_prefix)
    ctx = ConversionContext(section=section, user=user, path_prefix=path_prefix)
    return convert_section_to_author_blocks(section_value, ctx=ctx)


def overview_to_author_blocks(overview_value: list[dict]) -> list[dict]:
    """Backward-compatible wrapper for overview serialization."""
    return section_to_author_blocks(overview_value, path_prefix="overview")
