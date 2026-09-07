"""Sanitize editor API rich text through Wagtail's feature-based exporter."""

from __future__ import annotations

import json
import logging
from html.parser import HTMLParser
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from wagtail import blocks
from wagtail.admin.rich_text.converters.contentstate import ContentstateConverter
from wagtail.rich_text import RichText, features as feature_registry

from .errors import EditorValidationError

logger = logging.getLogger(__name__)
_RICH_TEXT_INPUT_ERRORS = (AssertionError, IndexError, KeyError, TypeError, ValueError, OverflowError)


class _RichTextInput(HTMLParser):
    """Inspect input metadata; ContentState export remains the sanitizer."""

    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path
        self.block_keys: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "embed":
            raise EditorValidationError(
                {
                    self.path: [
                        {"code": "inline_embed", "message": "Use structured media blocks instead of inline embeds."}
                    ]
                }
            )
        key = dict(attrs).get("data-block-key")
        if key is not None:
            self.block_keys.add(key)


def _rich_text_features(block: blocks.RichTextBlock) -> list[str]:
    features = block.features
    if features is None:
        editor = getattr(settings, "WAGTAILADMIN_RICH_TEXT_EDITORS", {}).get(block.editor, {})
        features = (editor.get("OPTIONS") or {}).get("features")
    if features is None:
        features = feature_registry.get_default_features()
    # Rich-text embeds bypass the structured media blocks' permission/probe
    # checks; oEmbed conversion can also fetch remote providers at author time.
    return [feature for feature in features if feature not in {"image", "embed"}]


def sanitize_rich_text(block: blocks.RichTextBlock, value: RichText, *, path: str) -> RichText:
    """Rebuild database HTML without accepting raw markup from API callers."""
    # Configuration failures are operator errors, not invalid author input.
    try:
        features = _rich_text_features(block)
        # The converter owns a mutable parser, so never cache/share it across requests.
        converter = ContentstateConverter(features)
    except Exception as exc:
        # Do not let custom blocks' conversion-error envelopes downgrade a
        # configuration TypeError/KeyError/etc. to a silent client error.
        raise ImproperlyConfigured("Unable to initialize editor API rich-text conversion.") from exc
    try:
        if not isinstance(value.source, str):
            raise TypeError("Expected a rich-text string.")
        if not (value.source or "").strip():
            return RichText("")
        incoming = _RichTextInput(path)
        incoming.feed(value.source)
        incoming.close()
        contentstate = json.loads(converter.from_database_format(value.source or ""))
        for item in contentstate["blocks"]:
            # Retain supplied keys (Wagtail comment anchors), but avoid adding
            # random keys to API-authored HTML. The exporter escapes retained keys.
            if item["key"] not in incoming.block_keys:
                item["key"] = None
        html = converter.to_database_format(json.dumps(contentstate))
    except _RICH_TEXT_INPUT_ERRORS as exc:
        # The parser assumes editor-generated HTML and can raise assertions,
        # indexing errors, or link-conversion errors for malformed API input.
        # Preserve an operator-visible trace, including failures in custom rules.
        logger.warning("Rejected editor API rich text at %s", path, exc_info=True)
        raise EditorValidationError({path: [{"code": "invalid", "message": "Invalid rich text."}]}) from exc
    return RichText(html)


def sanitize_block_value(block: blocks.Block, value: Any, *, path: str) -> Any:
    """Sanitize native block values before validation, retaining container IDs."""
    if isinstance(block, blocks.RawHTMLBlock):
        raise EditorValidationError(
            {path: [{"code": "invalid", "message": "Raw HTML blocks are not accepted by the editor API."}]}
        )
    if isinstance(block, blocks.RichTextBlock):
        return sanitize_rich_text(block, value, path=path)
    if isinstance(block, blocks.StructBlock):
        for name, child in block.child_blocks.items():
            value[name] = sanitize_block_value(child, value[name], path=f"{path}.{name}")
    elif isinstance(block, blocks.ListBlock):
        for index, child in enumerate(value.bound_blocks):
            child.value = sanitize_block_value(block.child_block, child.value, path=f"{path}.{index}")
    elif isinstance(block, blocks.StreamBlock):
        for index, child in enumerate(value):
            child.value = sanitize_block_value(child.block, child.value, path=f"{path}.{index}.value")
    return value
