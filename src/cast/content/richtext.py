"""Sanitize rich text without depending on a transport framework."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Literal, TypeAlias

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from wagtail import blocks
from wagtail.admin.rich_text.converters.contentstate import ContentstateConverter
from wagtail.rich_text import RichText, features as feature_registry

from .errors import ErrorCollector

logger = logging.getLogger(__name__)
_RICH_TEXT_INPUT_ERRORS = (AssertionError, IndexError, KeyError, TypeError, ValueError, OverflowError)


class _InlineEmbedError(Exception):
    """An inline embed bypassed the structured media boundary."""


RichTextLeaf: TypeAlias = blocks.RichTextBlock | blocks.RawHTMLBlock
LeafFn = Callable[[RichTextLeaf, Any, str], Any]


@dataclass(frozen=True)
class NormalizedRichText:
    """Read-only normalization result for stored rich text."""

    source: str
    normalized: str | None
    classification: Literal["identical", "normalized", "rejected"]
    errors: dict[str, list[dict[str, str]]]


class _RichTextInput(HTMLParser):
    """Inspect input metadata; ContentState export remains the sanitizer."""

    def __init__(self) -> None:
        super().__init__()
        self.block_keys: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "embed":
            raise _InlineEmbedError
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


def sanitize_rich_text(
    block: blocks.RichTextBlock,
    value: RichText,
    *,
    path: str,
    errors: ErrorCollector,
) -> RichText | None:
    """Rebuild database HTML, returning ``None`` exactly when an error is added."""
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
        incoming = _RichTextInput()
        incoming.feed(value.source)
        incoming.close()
        contentstate = json.loads(converter.from_database_format(value.source or ""))
        for item in contentstate["blocks"]:
            # Retain supplied keys (Wagtail comment anchors), but avoid adding
            # random keys to API-authored HTML. The exporter escapes retained keys.
            if item["key"] not in incoming.block_keys:
                item["key"] = None
        html = converter.to_database_format(json.dumps(contentstate))
    except _InlineEmbedError:
        errors.add(path, "inline_embed", "Use structured media blocks instead of inline embeds.")
        return None
    except _RICH_TEXT_INPUT_ERRORS:
        # The parser assumes editor-generated HTML and can raise assertions,
        # indexing errors, or link-conversion errors for malformed API input.
        # Preserve an operator-visible trace, including failures in custom rules.
        logger.warning("Rejected editor API rich text at %s", path, exc_info=True)
        errors.add(path, "invalid", "Invalid rich text.")
        return None
    return RichText(html)


def map_rich_text_leaves(block: blocks.Block, value: Any, *, path: str, fn: LeafFn) -> Any:
    """Map leaves in place, retaining IDs; callback failures leave prior mutations."""
    if isinstance(block, (blocks.RichTextBlock, blocks.RawHTMLBlock)):
        return fn(block, value, path)
    if isinstance(block, blocks.StructBlock):
        for name, child in block.child_blocks.items():
            value[name] = map_rich_text_leaves(child, value[name], path=f"{path}.{name}", fn=fn)
    elif isinstance(block, blocks.ListBlock):
        for index, child in enumerate(value.bound_blocks):
            child.value = map_rich_text_leaves(block.child_block, child.value, path=f"{path}.{index}", fn=fn)
    elif isinstance(block, blocks.StreamBlock):
        for index, child in enumerate(value):
            child.value = map_rich_text_leaves(child.block, child.value, path=f"{path}.{index}.value", fn=fn)
    return value


def sanitize_block_value(block: blocks.Block, value: Any, *, path: str, errors: ErrorCollector) -> Any:
    """Sanitize native values in place, retaining IDs and visiting every leaf.

    Rejected leaves become ``None`` in the returned, possibly partially
    mutated value. Callers must treat any new collector error as failure and
    must not validate or persist that returned container.
    """

    def sanitize_leaf(block: RichTextLeaf, value: Any, path: str) -> Any:
        if isinstance(block, blocks.RawHTMLBlock):
            errors.add(path, "invalid", "Raw HTML blocks are not accepted by the editor API.")
            return None
        before = len(errors)
        result = sanitize_rich_text(block, value, path=path, errors=errors)
        if result is None and len(errors) == before:
            raise RuntimeError("Rich-text sanitization returned no value without recording an error.")
        return result

    return map_rich_text_leaves(block, value, path=path, fn=sanitize_leaf)


def normalize_rich_text(block: blocks.RichTextBlock, source: str) -> NormalizedRichText:
    """Classify stored rich text without persisting changes or requiring a user."""
    errors = ErrorCollector()
    try:
        result = sanitize_rich_text(block, RichText(source), path="value", errors=errors)
    except Exception:
        logger.exception("Unable to normalize stored rich text.")
        errors.add("value", "normalization_failed", "Rich-text normalization failed.")
        result = None
    if result is None and not errors:
        logger.error("Rich-text normalization returned no value without recording an error.")
        errors.add("value", "normalization_failed", "Rich-text normalization failed.")
    if errors or result is None:
        return NormalizedRichText(source, None, "rejected", errors.error_map)
    classification: Literal["identical", "normalized"] = "identical" if result.source == source else "normalized"
    return NormalizedRichText(source, result.source, classification, errors.error_map)
