import pytest
from django.test import override_settings
from wagtail import blocks

from cast.api.editor.body import _media_ref_is_available, author_blocks_to_section
from cast.api.editor.errors import EditorValidationError
from cast.content.blocks import (
    UNSUPPORTED,
    AudioConverter,
    CodeConverter,
    ConversionContext,
    GenericBlockConverter,
    ImageConverter,
    ParagraphConverter,
    VideoConverter,
    content_converters,
)
from cast.content.errors import ErrorCollector


def test_content_converters_without_section_returns_partial_builtins_only():
    converters = content_converters(None)

    assert set(converters) == {"paragraph", "embed", "code", "image", "audio", "video"}
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


def test_code_converter_validates_and_reads_curated_fields():
    converter = CodeConverter()
    ctx = ConversionContext(section="overview", user=None)
    errors = ErrorCollector()

    assert converter.to_stream({"language": "", "extra": "x"}, ctx=ctx, path="overview.0.value", errors=errors) is None
    assert errors.error_map == {
        "overview.0.value.language": [{"code": "required", "message": "Code block 'language' is required."}],
        "overview.0.value.source": [{"code": "required", "message": "Code block 'source' is required."}],
    }
    assert converter.to_author({"language": "py", "source": "pass", "extra": "x"}, ctx=ctx) == {
        "language": "py",
        "source": "pass",
    }
    assert converter.to_author({"language": "py"}, ctx=ctx) is UNSUPPORTED


@pytest.mark.parametrize(
    ("converter_type", "patch_target", "message"),
    [
        (ImageConverter, "cast.content.blocks.get_choosable_image", "Image 7 does not exist or is not accessible."),
        (AudioConverter, "cast.content.blocks.get_choosable_audio", "Referenced media is not available."),
        (VideoConverter, "cast.content.blocks.get_choosable_video", "Referenced media is not available."),
    ],
)
def test_media_converter_preserves_not_found_message_and_skips_read_filter_without_user(
    mocker, converter_type, patch_target, message
):
    resolver = mocker.patch(patch_target, return_value=None)
    converter = converter_type()
    ctx = ConversionContext(section="overview", user=object())
    errors = ErrorCollector()

    assert converter.to_stream({"id": 7}, ctx=ctx, path="overview.0.value", errors=errors) is None
    assert errors.error_map == {"overview.0.value.id": [{"code": "not_found", "message": message}]}
    assert converter.to_author(7, ctx=ctx) is UNSUPPORTED
    assert converter.to_author(7, ctx=ConversionContext(section="overview", user=None)) == {"id": 7}
    assert resolver.call_args_list == [mocker.call(7, ctx.user), mocker.call(7, ctx.user)]


@pytest.mark.parametrize(
    ("block_type", "patch_target"),
    [
        ("image", "cast.content.media_refs.get_choosable_image"),
        ("audio", "cast.content.media_refs.get_choosable_audio"),
        ("video", "cast.content.media_refs.get_choosable_video"),
    ],
)
def test_compatibility_media_availability_helper(mocker, block_type, patch_target):
    checker = mocker.patch(patch_target, return_value=True)

    assert _media_ref_is_available(block_type, 7, "user")
    checker.assert_called_once_with(7, "user")


def test_missing_converter_cannot_reinterpret_a_supported_type_as_gallery(mocker):
    mocker.patch("cast.api.editor.body.content_converters", return_value={})

    with pytest.raises(EditorValidationError) as exc_info:
        author_blocks_to_section(
            [{"type": "code", "value": [{"id": 1}]}],
            user=None,
            path_prefix="overview",
        )

    assert exc_info.value.error_map == {
        "overview.0.type": [{"code": "unsupported_block_type", "message": "Block type 'code' is not supported."}]
    }
