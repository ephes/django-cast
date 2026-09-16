from wagtail import blocks

from cast.content.errors import ErrorCollector
from cast.content.richtext import sanitize_block_value


def test_raw_html_inside_stream_block_records_nested_error():
    block = blocks.StreamBlock([("raw", blocks.RawHTMLBlock())])
    value = block.to_python([{"type": "raw", "value": "<script>alert(1)</script>"}])
    errors = ErrorCollector()

    result = sanitize_block_value(block, value, path="detail.0.value", errors=errors)

    assert result is None
    assert value[0].value == "<script>alert(1)</script>"
    assert errors.error_map == {
        "detail.0.value.0.value": [
            {"code": "invalid", "message": "Raw HTML blocks are not accepted by the editor API."}
        ]
    }
