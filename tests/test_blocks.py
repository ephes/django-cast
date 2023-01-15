from cast.blocks import CodeBlock


def test_code_block_value_is_none():
    """Make sure that None value in code block is rendered as empty string."""
    block = CodeBlock()
    assert block.render_basic(None) == ""
