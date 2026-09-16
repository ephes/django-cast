from cast.content.blocks import ConversionContext
from cast.content.errors import ErrorCollector
from cast.content.placeholders import placeholder_for, resolve_placeholder


def test_placeholder_for_pins_stored_type_and_position():
    assert placeholder_for(2, {"type": "embed", "value": "https://example.com"}, "detail") == {
        "type": "unsupported",
        "value": {"stored_type": "embed", "position": "detail.2"},
    }


def test_resolve_placeholder_preserves_an_explicit_empty_prefix():
    errors = ErrorCollector()
    stored = {"type": "embed", "value": "https://example.com"}
    ctx = ConversionContext(section="overview", user=None, existing_section=[stored], path_prefix="")
    placeholder = placeholder_for(0, stored, "")

    assert resolve_placeholder(
        placeholder["value"],
        ctx=ctx,
        path=".0",
        errors=errors,
    ) == (stored, 0)
    assert not errors


def test_conversion_context_defaults_path_prefix_to_section():
    assert ConversionContext(section="overview", user=None).path_prefix == "overview"
