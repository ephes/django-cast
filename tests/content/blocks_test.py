from django.test import override_settings
from wagtail import blocks

from cast.api.editor.body import author_blocks_to_section
from cast.content.blocks import GenericBlockConverter, ParagraphConverter, content_converters


def test_content_converters_without_section_returns_partial_builtins_only():
    converters = content_converters(None)

    assert set(converters) == {"paragraph", "embed"}
    assert all(converters[name].name == name for name in converters)


@override_settings(CAST_POST_BODY_BLOCKS={"overview": ["tests.custom_post_body_blocks.weeknote_links_block"]})
def test_content_converters_wrap_configured_blocks():
    converters = content_converters("overview")

    assert isinstance(converters["weeknote_links"], GenericBlockConverter)


def test_configured_blocks_cannot_shadow_builtins(mocker):
    mocker.patch(
        "cast.content.blocks.configured_content_blocks",
        return_value=[("paragraph", blocks.CharBlock())],
    )

    assert isinstance(content_converters("overview")["paragraph"], ParagraphConverter)


def test_custom_block_can_prepare_a_successful_none_value(mocker):
    class NullBlock(blocks.Block):
        def get_prep_value(self, value):
            return None

    mocker.patch(
        "cast.content.blocks.configured_content_blocks",
        return_value=[("nullable", NullBlock())],
    )

    assert author_blocks_to_section([{"type": "nullable", "value": None}], user=None, path_prefix="overview") == [
        {"type": "nullable", "value": None}
    ]
