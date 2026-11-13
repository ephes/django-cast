import pytest
from wagtail import blocks

from cast.content.blocks import UNSUPPORTED, ConversionContext, GenericBlockConverter


@pytest.mark.parametrize("shape", ["deep", "cycle", "tuple_cycle", "wide"])
@pytest.mark.parametrize("api", [False, True])
def test_custom_block_nested_output_is_bounded(shape, api):
    output = []
    if shape in {"cycle", "tuple_cycle"}:
        if shape == "tuple_cycle":
            output = (output,)
            output[0].append(output)
        else:
            output.append(output)
    elif shape == "deep":
        for _ in range(64):
            output = [output]
    else:
        output = [0] * 10001

    class SyntheticBlock(blocks.Block):
        def get_prep_value(self, value):
            return output

    class ApiBlock(SyntheticBlock):
        def get_api_representation(self, value, context=None):
            return output

    converter = GenericBlockConverter("synthetic", ApiBlock() if api else SyntheticBlock())
    assert converter.to_author("opaque original", ctx=ConversionContext(section="overview", user=None)) is UNSUPPORTED
