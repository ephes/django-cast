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


def _line_span(line_map: list[int]) -> str:
    # The parser gives a zero-based, half-open line range for the containing block.
    first, last = line_map[0] + 1, line_map[1]
    return f"line {first}" if first == last else f"lines {first}-{last}"


def markdown_to_author_blocks(source: str, *, path: str, errors: ErrorCollector) -> list[dict[str, Any]]:
    """Convert Markdown to ``paragraph`` and ``code`` author blocks.

    Consecutive top-level prose becomes one ``paragraph`` block. Top-level fenced
    and indented code blocks become ``code`` blocks; the fence info string's
    first word is the language, ``text`` when absent. Nested code and inline
    images are rejected with source locations.
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
    previous_error_count = len(errors)
    for token in tokens:
        if token.type == "inline" and any(child.type == "image" for child in token.children or []):
            location = _line_span(token.map)
            errors.add(path, "inline_image", f"Markdown images are not supported ({location}); use image blocks.")
        elif token.type in _CODE_TOKENS and token.level > 0:
            # Wagtail's rich-text conversion can collapse whitespace in <pre><code>.
            location = _line_span(token.map)
            errors.add(path, "nested_code", f"Nested Markdown code is not supported ({location}); unnest it.")
    if len(errors) != previous_error_count:
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
