"""Editor API adapters for transport-neutral rich-text sanitization."""

from __future__ import annotations

from typing import Any, cast

from wagtail import blocks
from wagtail.admin.rich_text.converters.contentstate import ContentstateConverter
from wagtail.rich_text import RichText

from ...content.errors import ErrorCollector
from ...content.richtext import (
    sanitize_block_value as _sanitize_block_value,
    sanitize_rich_text as _sanitize_rich_text,
)
from .errors import EditorValidationError

__all__ = ["ContentstateConverter", "sanitize_block_value", "sanitize_rich_text"]


def sanitize_rich_text(block: blocks.RichTextBlock, value: RichText, *, path: str) -> RichText:
    """Sanitize rich text and adapt collector failures to the editor API."""
    errors = ErrorCollector()
    result = _sanitize_rich_text(block, value, path=path, errors=errors)
    if errors:
        raise EditorValidationError(errors.error_map)
    return cast(RichText, result)


def sanitize_block_value(block: blocks.Block, value: Any, *, path: str) -> Any:
    """Sanitize a block value and adapt collector failures to the editor API."""
    errors = ErrorCollector()
    result = _sanitize_block_value(block, value, path=path, errors=errors)
    if errors:
        raise EditorValidationError(errors.error_map)
    return result
