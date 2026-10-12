"""Convert optional Markdown input into the canonical author block list.

The Markdown parser is an optional dependency (``django-cast[markdown]``). It is
imported lazily so installs without the extra keep working; callers receive a
``markdown_unavailable`` error instead of an ``ImportError``.

The conversion only produces author blocks. Callers must run the result through
the normal block conversion so paragraph HTML is sanitized by the same
rich-text pipeline as directly submitted blocks.
"""

from __future__ import annotations

from typing import Any

from .errors import ErrorCollector

MARKDOWN_EXTRA = "django-cast[markdown]"
DEFAULT_CODE_LANGUAGE = "text"
_CODE_TOKENS = frozenset({"fence", "code_block"})


def _markdown_parser() -> Any | None:
    try:
        from markdown_it import MarkdownIt
    except ImportError:
        return None
    # CommonMark without raw HTML: embedded HTML is escaped and kept as text
    # instead of being passed to the rich-text sanitizer as markup.
    return MarkdownIt("commonmark", {"html": False})


def _code_block(token: Any) -> dict[str, Any]:
    info = token.info.strip().split()
    language = info[0] if info else DEFAULT_CODE_LANGUAGE
    return {"type": "code", "value": {"language": language, "source": token.content.removesuffix("\n")}}


def _image_locations(tokens: list[Any]) -> list[str]:
    """Return the source line span of each text block that contains an image."""
    locations = []
    for token in tokens:
        if token.type == "inline" and any(child.type == "image" for child in token.children or []):
            # ``map`` is the block's [start, end) line range. Inline tokens carry no
            # reliable per-image line, so report the whole span rather than guess.
            first, last = token.map[0] + 1, token.map[1]
            locations.append(f"line {first}" if first == last else f"lines {first}-{last}")
    return locations


def markdown_to_author_blocks(source: str, *, path: str, errors: ErrorCollector) -> list[dict[str, Any]]:
    """Convert Markdown to ``paragraph`` and ``code`` author blocks.

    Consecutive top-level prose becomes one ``paragraph`` block. Top-level fenced
    and indented code blocks become ``code`` blocks; the fence info string's
    first word is the language, ``text`` when absent. Inline images are rejected
    because media must use the structured, permission-checked blocks; the error
    names the source line span of each paragraph or heading containing images.
    """
    parser = _markdown_parser()
    if parser is None:
        errors.add(
            path,
            "markdown_unavailable",
            f"Markdown input requires the optional {MARKDOWN_EXTRA} extra; send a block list instead.",
        )
        return []

    env: dict[str, Any] = {}
    tokens = parser.parse(source, env)
    image_locations = _image_locations(tokens)
    for location in image_locations:
        errors.add(path, "inline_image", f"Markdown images are not supported ({location}); use image blocks.")
    if image_locations:
        return []

    blocks: list[dict[str, Any]] = []
    prose: list[Any] = []

    def flush_prose() -> None:
        html = parser.renderer.render(prose, parser.options, env).strip()
        if html:
            blocks.append({"type": "paragraph", "value": html})
        prose.clear()

    for token in tokens:
        if token.level == 0 and token.type in _CODE_TOKENS:
            flush_prose()
            blocks.append(_code_block(token))
        else:
            prose.append(token)
    flush_prose()
    return blocks
