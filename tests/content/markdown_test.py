import sys

import pytest

from cast.content.errors import ErrorCollector
from cast.content.markdown import markdown_to_author_blocks


def convert(source):
    errors = ErrorCollector()
    blocks = markdown_to_author_blocks(source, path="overview_markdown", errors=errors)
    return blocks, errors.error_map


def test_prose_between_code_blocks_becomes_paragraph_blocks():
    source = "## Notes\n\nSome *text*.\n\n```python extra\nprint('hi')\n```\n\n    indented\n\nAfter."

    blocks, errors = convert(source)

    assert errors == {}
    assert blocks == [
        {"type": "paragraph", "value": "<h2>Notes</h2>\n<p>Some <em>text</em>.</p>"},
        {"type": "code", "value": {"language": "python", "source": "print('hi')"}},
        {"type": "code", "value": {"language": "text", "source": "indented"}},
        {"type": "paragraph", "value": "<p>After.</p>"},
    ]


def test_empty_markdown_is_an_empty_block_list():
    assert convert("") == ([], {})
    assert convert("  \n\n") == ([], {})


def test_nested_code_stays_in_the_paragraph():
    blocks, errors = convert("- item\n\n  ```\n  nested\n  ```\n")

    assert errors == {}
    assert [block["type"] for block in blocks] == ["paragraph"]
    assert "<pre><code>nested\n</code></pre>" in blocks[0]["value"]


def test_raw_html_is_escaped_not_passed_through():
    blocks, errors = convert('<script>alert(1)</script>\n\nText <img src=x onerror="alert(1)">')

    assert errors == {}
    html = "".join(block["value"] for block in blocks)
    assert "<script" not in html
    assert "<img" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_dangerous_link_schemes_are_not_rendered_as_links():
    blocks, errors = convert("[a](javascript:alert(1)) [b](vbscript:x) [c](data:text/html,x) [d](https://example.com)")

    assert errors == {}
    assert blocks == [
        {
            "type": "paragraph",
            "value": "<p>[a](javascript:alert(1)) [b](vbscript:x) [c](data:text/html,x) "
            '<a href="https://example.com">d</a></p>',
        }
    ]


def image_errors(*locations):
    return {
        "overview_markdown": [
            {"code": "inline_image", "message": f"Markdown images are not supported ({location}); use image blocks."}
            for location in locations
        ]
    }


def test_inline_images_are_rejected_with_line_numbers():
    blocks, errors = convert("Intro\n\n![alt](https://example.com/a.png)\n\n# ![x](y)")

    assert blocks == []
    assert errors == image_errors("line 3", "line 5")


@pytest.mark.parametrize(
    ("source", "location"),
    [
        ("first line\nsecond line\n![a](url)\n\nlater", "lines 1-3"),
        ("Intro\n\n- item\n  text ![a](url)\n- other", "lines 3-4"),
        ("> quoted\n> ![a](url) and ![b](url)", "lines 1-2"),
        ("[![badge](img)](https://example.com)", "line 1"),
    ],
)
def test_image_errors_name_the_containing_line_span(source, location):
    blocks, errors = convert(source)

    assert blocks == []
    assert errors == image_errors(location)


def test_missing_optional_dependency_is_a_field_error(monkeypatch):
    # A ``None`` entry makes ``import markdown_it`` raise ImportError.
    monkeypatch.setitem(sys.modules, "markdown_it", None)

    blocks, errors = convert("Text")

    assert blocks == []
    assert errors == {
        "overview_markdown": [
            {
                "code": "markdown_unavailable",
                "message": "Markdown input requires the optional django-cast[markdown] extra; "
                "send a block list instead.",
            }
        ]
    }


@pytest.mark.parametrize("source", ["a" * 10, "*" * 10_000 + "x", "> " * 1_000 + "deep"])
def test_pathological_input_converts(source):
    blocks, errors = convert(source)

    assert errors == {}
    assert all(block["type"] == "paragraph" for block in blocks)
