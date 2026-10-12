from __future__ import annotations

from typing import Any

from ...content.blocks import ConversionContext
from ...content.convert import (
    author_blocks_to_section as convert_author_blocks_to_section,
    content_section,
    section_to_author_blocks as convert_section_to_author_blocks,
)
from ...content.errors import ContentValidationError, ErrorCollector
from ...content.markdown import markdown_to_author_blocks
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


def markdown_field(section: str) -> str:
    """Request field carrying the Markdown alternative for a body section."""
    return f"{section}_markdown"


def markdown_to_section(source: str, *, user: Any, section: str) -> list[dict]:
    """Convert Markdown into a body-section value through the canonical block pipeline.

    The generated ``paragraph``/``code`` author blocks are validated and sanitized
    exactly like a submitted block list. Errors are reported under
    ``<section>_markdown``; indexed paths refer to the generated block list.
    """
    field = markdown_field(section)
    errors = ErrorCollector()
    blocks = markdown_to_author_blocks(source, path=field, errors=errors)
    if errors:
        raise EditorValidationError(errors.error_map)
    try:
        return author_blocks_to_section(blocks, user=user, path_prefix=section)
    except EditorValidationError as exc:
        raise EditorValidationError(
            {field + path.removeprefix(section): items for path, items in exc.error_map.items()}
        ) from exc


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
