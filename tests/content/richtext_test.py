import pytest
from django.test import override_settings
from wagtail import blocks
from wagtail.rich_text import RichText

from cast.content.errors import ErrorCollector
from cast.content.richtext import map_rich_text_leaves, normalize_rich_text, sanitize_block_value


def test_raw_html_inside_stream_block_records_nested_error():
    block = blocks.StreamBlock([("raw", blocks.RawHTMLBlock())])
    value = block.to_python([{"type": "raw", "value": "<script>alert(1)</script>"}])
    errors = ErrorCollector()

    result = sanitize_block_value(block, value, path="detail.0.value", errors=errors)

    assert result is value
    assert value[0].value is None
    assert errors.error_map == {
        "detail.0.value.0.value": [
            {"code": "invalid", "message": "Raw HTML blocks are not accepted by the editor API."}
        ]
    }


def test_multiple_raw_html_and_rich_text_leaves_are_rejected_together():
    block = blocks.StructBlock(
        [
            ("first_raw", blocks.RawHTMLBlock()),
            ("text", blocks.RichTextBlock()),
            ("second_raw", blocks.RawHTMLBlock()),
        ]
    )
    value = block.to_python(
        {
            "first_raw": "<script>first()</script>",
            "text": "<li>Outside a list</li>",
            "second_raw": "<script>second()</script>",
        }
    )
    errors = ErrorCollector()

    result = sanitize_block_value(block, value, path="detail.0.value", errors=errors)

    assert result is value
    assert dict(value) == {"first_raw": None, "text": None, "second_raw": None}
    assert errors.error_map == {
        "detail.0.value.first_raw": [
            {"code": "invalid", "message": "Raw HTML blocks are not accepted by the editor API."}
        ],
        "detail.0.value.text": [{"code": "invalid", "message": "Invalid rich text."}],
        "detail.0.value.second_raw": [
            {"code": "invalid", "message": "Raw HTML blocks are not accepted by the editor API."}
        ],
    }


def test_map_rich_text_leaves_walks_struct_list_and_stream_values():
    block = blocks.StructBlock(
        [
            ("intro", blocks.RichTextBlock()),
            ("items", blocks.ListBlock(blocks.StructBlock([("text", blocks.RichTextBlock())]))),
            ("stream", blocks.StreamBlock([("text", blocks.RichTextBlock())])),
        ]
    )
    value = block.to_python(
        {
            "intro": "<p>Intro</p>",
            "items": [{"text": "<p>Item</p>"}],
            "stream": [{"type": "text", "value": "<p>Stream</p>"}],
        }
    )
    paths = []

    def record(_block, leaf_value, path):
        paths.append(path)
        return RichText(leaf_value.source.replace("p>", "strong>"))

    result = map_rich_text_leaves(block, value, path="body.0.value", fn=record)

    assert paths == ["body.0.value.intro", "body.0.value.items.0.text", "body.0.value.stream.0.value"]
    assert result["intro"].source == "<strong>Intro</strong>"
    assert result["items"][0]["text"].source == "<strong>Item</strong>"
    assert result["stream"][0].value.source == "<strong>Stream</strong>"


def test_normalize_rich_text_classifies_revision_style_source():
    block = blocks.RichTextBlock()

    identical = normalize_rich_text(block, "<p>Safe</p>")
    normalized = normalize_rich_text(block, '<p onclick="alert(1)">Safe</p>')
    rejected = normalize_rich_text(block, "<li>Outside a list</li>")

    assert (identical.classification, identical.normalized, identical.errors) == (
        "identical",
        "<p>Safe</p>",
        {},
    )
    assert (normalized.classification, normalized.normalized, normalized.errors) == (
        "normalized",
        "<p>Safe</p>",
        {},
    )
    assert rejected.classification == "rejected"
    assert rejected.normalized is None
    assert rejected.errors == {"value": [{"code": "invalid", "message": "Invalid rich text."}]}


def test_normalize_rich_text_never_raises_for_configuration_errors(caplog):
    with override_settings(WAGTAILADMIN_RICH_TEXT_EDITORS={"default": {"OPTIONS": {"features": 123}}}):
        result = normalize_rich_text(blocks.RichTextBlock(), "<p>Safe</p>")

    assert result.classification == "rejected"
    assert result.normalized is None
    assert result.errors["value"] == [{"code": "normalization_failed", "message": "Rich-text normalization failed."}]
    assert "Unable to normalize stored rich text" in caplog.text


def test_none_without_a_collected_error_is_never_silent(mocker, caplog):
    mocker.patch("cast.content.richtext.sanitize_rich_text", return_value=None)

    with pytest.raises(RuntimeError, match="without recording an error"):
        sanitize_block_value(
            blocks.RichTextBlock(),
            RichText("<p>Safe</p>"),
            path="body.0.value",
            errors=ErrorCollector(),
        )

    normalized = normalize_rich_text(blocks.RichTextBlock(), "<p>Safe</p>")
    assert normalized.errors == {
        "value": [{"code": "normalization_failed", "message": "Rich-text normalization failed."}]
    }
    assert "returned no value without recording an error" in caplog.text
