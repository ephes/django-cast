import pytest

from cast.content.blocks import ConversionContext
from cast.content.convert import convert_author_blocks
from cast.content.errors import ErrorCollector


def test_errored_blocks_never_contribute_partial_output():
    errors = ErrorCollector()
    ctx = ConversionContext(section="overview", user=None)

    result = convert_author_blocks(
        [
            {"type": "paragraph", "value": 1},
            {"type": "code", "value": {"language": "python"}},
            {"type": "gallery", "value": []},
            {"type": "embed", "value": "https://example.com"},
            {"type": "unknown", "value": "value"},
        ],
        ctx=ctx,
        errors=errors,
    )

    assert result == []
    assert errors.error_map == {
        "overview.0.value": [{"code": "invalid", "message": "Expected a string value."}],
        "overview.1.value.source": [{"code": "required", "message": "Code block 'source' is required."}],
        "overview.2.value": [{"code": "invalid", "message": "Gallery value must be a non-empty list of image refs."}],
        "overview.3.type": [{"code": "unsupported_block_type", "message": "Block type 'embed' is not supported."}],
        "overview.4.type": [{"code": "unsupported_block_type", "message": "Block type 'unknown' is not supported."}],
    }


def test_non_list_input_is_collected_without_raising():
    errors = ErrorCollector()

    assert (
        convert_author_blocks(
            "not a list",
            ctx=ConversionContext(section="overview", user=None),
            errors=errors,
        )
        == []
    )
    assert errors.error_map == {"overview": [{"code": "invalid", "message": "overview must be a list of blocks."}]}


def test_conversion_requires_a_path_prefix_or_section():
    with pytest.raises(ValueError, match="path_prefix is required when section is None"):
        convert_author_blocks([], ctx=ConversionContext(section=None, user=None), errors=ErrorCollector())
